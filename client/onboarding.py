"""入会话前测评：问卷、排序、基因报告与基础记忆。

数据只写进当前档案的本地加密库（单条 `kind=mi_assessment` 记录），
不上传云端。基因报告原文另存到 `<档案目录>/uploads/gene/`，便于复核。
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from mhagent.mi import QuestionBank, QuizError, build_memory_text, fuse_scores, score_quiz
from mhagent.mi.memory import REPORT_DIGEST_VERSION, build_report_digest
from mhagent.mi.report import analyze_report, build_meta

ASSESSMENT_KIND = "mi_assessment"
GENE_DIR = "uploads/gene"
MAX_GENE_BYTES = 10 * 1024 * 1024
ALLOWED_SUFFIXES = (".pdf", ".docx", ".txt")
MAX_TEXT_CHARS = 12000
CONFIDENCE_LEVELS = ("high", "medium", "low")


class OnboardingError(ValueError):
    """测评数据不合法（对应 HTTP 400）。"""


class OnboardingRequired(Exception):
    """测评尚未完成，后端拒绝对话（对应 HTTP 409）。"""


class GeneExtractError(Exception):
    """基因报告未能识别出 8 项分数（对应 HTTP 422）。"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_name(filename: str) -> str:
    name = Path(str(filename or "gene")).name
    cleaned = re.sub(r"[^\w.\u4e00-\u9fff-]+", "_", name).strip("._") or "gene"
    return cleaned[:80]


def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _extract_docx(data: bytes) -> str:
    from docx import Document

    document = Document(BytesIO(data))
    parts = [para.text for para in document.paragraphs if para.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def _extract_text(data: bytes) -> str:
    for encoding in ("utf-8", "gb18030", "utf-16"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def _score_value(value):
    """把报告分数归一化到 0-120 的一位小数；非法值返回 None。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(min(120.0, max(0.0, number)), 1)


_GENE_PROMPT = """你是基因检测报告的结构化抽取器。用户会上传一份报告文本。
请只输出一个 JSON 对象，不要输出解释、不要用 Markdown 代码块，格式如下：
{"scores":{"lang":0-100,"logic":0-100,"visual":0-100,"nature":0-100,"music":0-100,"body":0-100,"social":0-100,"inner":0-100},"confidence":"high|medium|low","notes":"原文依据摘要，不超过100字"}
其中 key 对应八大智能：lang 语言、logic 逻辑数学、visual 视觉空间、nature 自然观察、
music 音乐、body 肢体动觉、social 人际沟通、inner 个人内省。
若报告只给出部分智能，也必须根据原文合理换算或按报告口径填写；完全无法识别时输出
{"error":"unrecognized"}。"""


def parse_gene_payload(text: str) -> dict:
    """从模型输出里解析出 8 项分数，失败抛 `GeneExtractError`。"""
    raw = str(text or "").strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise GeneExtractError("未能从报告中识别出 8 项分数")
    try:
        payload = json.loads(raw[start : end + 1])
    except json.JSONDecodeError as exc:
        raise GeneExtractError("未能从报告中识别出 8 项分数") from exc
    if not isinstance(payload, dict) or payload.get("error"):
        raise GeneExtractError("未能从报告中识别出 8 项分数")
    scores = payload.get("scores")
    if not isinstance(scores, dict):
        raise GeneExtractError("未能从报告中识别出 8 项分数")
    cleaned: dict[str, int] = {}
    for key, value in scores.items():
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if 0 <= number <= 100:
            cleaned[str(key)] = int(round(number))
    if len(cleaned) < 8:
        raise GeneExtractError("未能从报告中识别出 8 项分数")
    confidence = str(payload.get("confidence") or "").lower()
    if confidence not in CONFIDENCE_LEVELS:
        confidence = "medium"
    return {
        "scores": cleaned,
        "confidence": confidence,
        "notes": str(payload.get("notes") or "")[:300],
    }


class OnboardingService:
    """一个档案一个测评服务实例。"""

    def __init__(self, store, llm, data_dir, *, nickname: str = "", clock=None, bank=None):
        self.store = store
        self.llm = llm
        self.data_dir = Path(data_dir)
        self.nickname = str(nickname or "")
        self._clock = clock
        self.bank = bank or QuestionBank.load()

    # ---- 基础 ----
    def now(self) -> datetime:
        current = self._clock() if self._clock else _now()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current.astimezone(timezone.utc)

    def _default(self) -> dict:
        return {
            "status": "draft",
            "answers": {},
            "rankings": {"intel": [], "ind": {}},
            "gene": None,
            "result": None,
            "memory_text": "",
            "created_at": self.now().isoformat(),
            "updated_at": self.now().isoformat(),
            "completed_at": None,
        }

    def _load(self) -> tuple[int | None, dict]:
        records = self.store.list_records(ASSESSMENT_KIND)
        if not records:
            return None, self._default()
        record = records[0]
        payload = dict(record["payload"])
        base = self._default()
        base.update(payload)
        base.setdefault("rankings", {"intel": [], "ind": {}})
        return record["id"], base

    def _save(self, record_id: int | None, payload: dict) -> dict:
        payload["updated_at"] = self.now().isoformat()
        if record_id is None:
            self.store.add_record(ASSESSMENT_KIND, payload, created_at=self.now())
        else:
            self.store.update_record(record_id, payload)
        return payload

    # ---- 查询 ----
    @property
    def completed(self) -> bool:
        _, payload = self._load()
        return payload.get("status") == "completed"

    def get(self) -> dict:
        _, payload = self._load()
        result = dict(payload)
        result["progress"] = self._progress(payload)
        return result

    def memory_text(self) -> str:
        _, payload = self._load()
        if payload.get("status") != "completed":
            return ""
        return str(payload.get("memory_text") or "")

    def ensure_ready(self) -> None:
        if not self.completed:
            raise OnboardingRequired("请先完成入学测评")

    def questionnaire(self) -> dict:
        """返回前端渲染用的题库。"""
        return {
            "version": self.bank.version,
            "scale": {"min": self.bank.scale_min, "max": self.bank.scale_max, "labels": self.bank.labels},
            "intelligences": [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "indicators": item["indicators"],
                }
                for item in self.bank.intelligences
            ],
            "questions": self.bank.questions,
        }

    def _progress(self, payload: dict) -> dict:
        scored = score_quiz(payload.get("answers") or {}, self.bank)
        rankings = payload.get("rankings") or {}
        intel_ready = len(rankings.get("intel") or []) == len(self.bank.intel_ids)
        ind_map = rankings.get("ind") or {}
        ind_ready = all(
            len(ind_map.get(iid) or []) == len(self.bank.indicator_ids(iid))
            for iid in self.bank.intel_ids
        )
        return {
            "done_items": scored["done_items"],
            "total_items": 40,
            "quiz_valid": scored["valid"],
            "intel_ranked": intel_ready,
            "ind_ranked": ind_ready,
        }

    # ---- 写入 ----
    def save_answers(self, answers) -> dict:
        if not isinstance(answers, dict):
            raise OnboardingError("answers 必须是对象")
        record_id, payload = self._load()
        current = dict(payload.get("answers") or {})
        for key, value in answers.items():
            try:
                qid = int(key)
                score = int(value)
            except (TypeError, ValueError):
                continue
            if not 1 <= qid <= 80:
                continue
            if score == 0:
                current.pop(str(qid), None)
                continue
            if 1 <= score <= 5:
                current[str(qid)] = score
        payload["answers"] = current
        self._save(record_id, payload)
        return self.get()

    def save_rankings(self, rankings) -> dict:
        if not isinstance(rankings, dict):
            raise OnboardingError("rankings 必须是对象")
        record_id, payload = self._load()
        intel = rankings.get("intel", (payload.get("rankings") or {}).get("intel"))
        ind = rankings.get("ind", (payload.get("rankings") or {}).get("ind"))
        cleaned_intel = self._clean_order(intel, self.bank.intel_ids, "智能", partial=True)
        cleaned_ind: dict[str, list[str]] = {}
        raw_ind = ind if isinstance(ind, dict) else {}
        for iid in self.bank.intel_ids:
            cleaned_ind[iid] = self._clean_order(
                raw_ind.get(iid), self.bank.indicator_ids(iid), f"{iid} 组内指标", partial=True
            )
        payload["rankings"] = {"intel": cleaned_intel, "ind": cleaned_ind}
        self._save(record_id, payload)
        return self.get()

    def _clean_order(self, order, expected: list[str], label: str, *, partial: bool) -> list[str]:
        if order in (None, [], ()):
            if not partial:
                raise OnboardingError(f"{label}排序不完整，请先完成排序")
            return []
        if not isinstance(order, (list, tuple)):
            raise OnboardingError(f"{label}排序格式不正确")
        cleaned: list[str] = []
        for item in order:
            value = str(item)
            if value not in expected:
                raise OnboardingError(f"{label}包含未知项：{value}")
            if value in cleaned:
                raise OnboardingError(f"{label}包含重复项：{value}")
            cleaned.append(value)
        if not partial and len(cleaned) != len(expected):
            raise OnboardingError(f"{label}排序不完整")
        return cleaned

    # ---- 基因报告 ----
    def attach_gene(self, data: bytes, filename: str) -> dict:
        suffix = Path(str(filename or "")).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise OnboardingError("只支持 PDF、DOCX、TXT 格式的基因检测报告")
        if not data:
            raise OnboardingError("上传的文件为空")
        if len(data) > MAX_GENE_BYTES:
            raise OnboardingError("文件超过 10MB 上限")
        try:
            if suffix == ".pdf":
                text = _extract_pdf(data)
            elif suffix == ".docx":
                text = _extract_docx(data)
            else:
                text = _extract_text(data)
        except Exception as exc:
            raise GeneExtractError("报告文件无法解析，请换一份文件或跳过") from exc
        text = (text or "").strip()
        if len(text) < 20:
            raise GeneExtractError("报告中几乎没有可读文字，请换一份文件或跳过")

        source_path = self._save_gene_file(data, filename, text)
        messages = [
            {"role": "system", "content": _GENE_PROMPT},
            {"role": "user", "content": text[:MAX_TEXT_CHARS]},
        ]
        try:
            response = self.llm.chat(messages, max_tokens=600)
            content = getattr(response, "content", response)
        except Exception as exc:
            raise GeneExtractError("基因报告解析失败，可重试或跳过") from exc
        parsed = parse_gene_payload(content)
        missing = [iid for iid in self.bank.intel_ids if iid not in parsed["scores"]]
        if missing:
            raise GeneExtractError("报告中缺少部分智能分数，可重试或跳过")

        record_id, payload = self._load()
        payload["gene"] = {
            "filename": _safe_name(filename),
            "confidence": parsed["confidence"],
            "scores": parsed["scores"],
            "notes": parsed["notes"],
            "path": source_path,
            "uploaded_at": self.now().isoformat(),
        }
        if payload.get("status") == "completed" and payload.get("result"):
            self._refresh_after_gene(payload)
        self._save(record_id, payload)
        return dict(payload["gene"])

    def _save_gene_file(self, data: bytes, filename: str, text: str) -> str:
        target_dir = self.data_dir / GENE_DIR
        target_dir.mkdir(parents=True, exist_ok=True)
        stamp = self.now().strftime("%Y%m%d%H%M%S")
        target = target_dir / f"{stamp}_{_safe_name(filename)}"
        target.write_bytes(data)
        target.with_suffix(target.suffix + ".txt").write_text(text, encoding="utf-8")
        return str(target)

    def clear_gene(self) -> dict:
        record_id, payload = self._load()
        payload["gene"] = None
        if payload.get("status") == "completed" and payload.get("result"):
            self._refresh_after_gene(payload)
        self._save(record_id, payload)
        return self.get()

    # ---- 完成 ----
    def _fuse_result(self, payload: dict) -> dict:
        scored = score_quiz(payload.get("answers") or {}, self.bank)
        if not scored["valid"]:
            raise OnboardingError("问卷未达到有效门槛：至少需要完成 10 项能力指标（20 题）")

        rankings = payload.get("rankings") or {}
        intel_order = self._clean_order(
            rankings.get("intel"), self.bank.intel_ids, "智能", partial=False
        )
        ind_map: dict[str, list[str]] = {}
        for iid in self.bank.intel_ids:
            ind_map[iid] = self._clean_order(
                (rankings.get("ind") or {}).get(iid),
                self.bank.indicator_ids(iid),
                f"{iid} 组内指标",
                partial=False,
            )

        try:
            return fuse_scores(scored, intel_order, ind_map, payload.get("gene"), self.bank)
        except QuizError as exc:
            raise OnboardingError(str(exc)) from exc

    @staticmethod
    def _assessment_source(gene=None) -> dict:
        source = {"kind": "assessment", "label": "基础测评（问卷 + 主观排序 + 可选基因融合）"}
        filename = str((gene or {}).get("filename") or "")
        if filename:
            source["label"] = f"基础测评 + 基因报告《{filename}》"
            source["gene"] = filename
        return source

    def _source_from_payload(self, payload: dict) -> dict:
        override = payload.get("report_override") or {}
        result = payload.get("result") or {}
        if override or result.get("fusion_version") == "REPORT-OVERRIDE":
            title = str(override.get("title") or "提交报告")
            return {"kind": "report", "label": f"会话提交报告《{title}》", **override}
        return self._assessment_source(payload.get("gene"))

    def _build_interpretation(self, result: dict, *, source: dict, gene=None) -> tuple[dict, str]:
        """生成解读报告要点摘要与会话记忆。"""
        meta = build_meta({"nickname": self.nickname, "age_range": ""}, {})
        analysis = analyze_report(result, meta)
        interpretation = {
            "version": REPORT_DIGEST_VERSION,
            "generated_at": self.now().isoformat(),
            "digest": build_report_digest(analysis),
            "source": source,
        }
        memory = build_memory_text(
            result,
            self.nickname,
            gene=gene,
            generated_at=self.now(),
            report=analysis,
            source=source,
        )
        return interpretation, memory

    def _refresh_after_gene(self, payload: dict) -> None:
        """测评完成后基因变更时重算结果与记忆；报告覆盖结果保持报告优先。"""
        result = payload.get("result") or {}
        if result.get("fusion_version") == "REPORT-OVERRIDE":
            return
        try:
            refreshed = self._fuse_result(payload)
        except OnboardingError:
            return
        interpretation, memory = self._build_interpretation(
            refreshed, source=self._assessment_source(payload.get("gene")), gene=payload.get("gene")
        )
        payload["result"] = refreshed
        payload["interpretation"] = interpretation
        payload["memory_text"] = memory
        payload.pop("report_override", None)

    def complete(self) -> dict:
        record_id, payload = self._load()
        if payload.get("status") == "completed":
            return {
                "result": payload.get("result"),
                "memory_text": payload.get("memory_text"),
                "interpretation": payload.get("interpretation"),
            }

        result = self._fuse_result(payload)
        interpretation, memory = self._build_interpretation(
            result, source=self._assessment_source(payload.get("gene")), gene=payload.get("gene")
        )
        payload["result"] = result
        payload["memory_text"] = memory
        payload["interpretation"] = interpretation
        payload.pop("report_override", None)
        payload["status"] = "completed"
        payload["completed_at"] = self.now().isoformat()
        self._save(record_id, payload)
        return {"result": result, "memory_text": memory, "interpretation": interpretation}

    def ensure_interpretation(self) -> None:
        """为已完成但缺少报告摘要的历史数据补齐摘要与记忆。"""
        record_id, payload = self._load()
        if payload.get("status") != "completed" or not payload.get("result"):
            return
        interpretation = payload.get("interpretation") or {}
        memory = str(payload.get("memory_text") or "")
        if (
            interpretation.get("version") == REPORT_DIGEST_VERSION
            and "【解读报告要点】" in memory
        ):
            return
        source = self._source_from_payload(payload)
        interpretation, memory = self._build_interpretation(
            payload["result"],
            source=source,
            gene=None if source.get("kind") == "report" else payload.get("gene"),
        )
        payload["interpretation"] = interpretation
        payload["memory_text"] = memory
        self._save(record_id, payload)

    def apply_report_scores(
        self,
        scores,
        *,
        title: str = "提交报告",
        report_id=None,
        filename: str = "",
    ) -> dict:
        """用会话提交报告的分数覆盖测评结果，并重算解读报告与记忆。"""
        record_id, payload = self._load()
        if payload.get("status") != "completed" or not payload.get("result"):
            return {
                "revised": False,
                "note": "当前成员尚未完成基础测评，报告已归档但未修正解读报告",
            }

        raw_intel = (scores or {}).get("intel") or {}
        raw_ind = (scores or {}).get("ind") or {}
        all_intel = list(self.bank.intel_ids)
        all_ind = [
            ind["id"]
            for intel in self.bank.intelligences
            for ind in intel["indicators"]
        ]
        intel_scores: dict[str, float] = {}
        for key, value in raw_intel.items():
            if key in all_intel:
                number = _score_value(value)
                if number is not None:
                    intel_scores[key] = number
        ind_scores: dict[str, float] = {}
        for key, value in raw_ind.items():
            if key in all_ind:
                number = _score_value(value)
                if number is not None:
                    ind_scores[key] = number

        if not intel_scores and not ind_scores:
            return {"revised": False, "note": "未从报告中解析出分数，解读报告未修正"}

        current = payload["result"]
        old_ind = current.get("ind") or {}
        old_intel = current.get("intel") or {}

        override_ind: dict[str, dict] = {}
        for intel in self.bank.intelligences:
            items = []
            for ind in intel["indicators"]:
                previous = old_ind.get(ind["id"]) or {}
                score = ind_scores.get(ind["id"])
                if score is None:
                    score = _score_value(previous.get("score")) or 0.0
                items.append(
                    {
                        "id": ind["id"],
                        "name": ind["name"],
                        "intelligence": intel["id"],
                        "quiz": score,
                        "inner": score,
                        "score": score,
                        "source": "report",
                    }
                )
            for rank, item in enumerate(sorted(items, key=lambda x: -x["score"]), 1):
                item["rank"] = rank
            for item in items:
                override_ind[item["id"]] = item

        override_intel: dict[str, dict] = {}
        for intel in self.bank.intelligences:
            values = [override_ind[ind["id"]]["score"] for ind in intel["indicators"]]
            score = intel_scores.get(intel["id"])
            if score is None:
                score = round(sum(values) / len(values), 1) if values else 0.0
            previous = old_intel.get(intel["id"]) or {}
            override_intel[intel["id"]] = {
                "id": intel["id"],
                "name": intel["name"],
                "inner": score,
                "score": score,
                "source": "report",
                "rank": previous.get("rank") or 99,
            }
        for rank, item in enumerate(
            sorted(override_intel.values(), key=lambda x: -x["score"]), 1
        ):
            item["rank"] = rank

        result = {
            "ind": override_ind,
            "intel": override_intel,
            "fusion_version": "REPORT-OVERRIDE",
            "gene_used": False,
        }
        missing_intel = [iid for iid in all_intel if iid not in intel_scores]
        missing_ind = [iid for iid in all_ind if iid not in ind_scores]
        coverage = {
            "intel": len(intel_scores),
            "ind": len(ind_scores),
            "missing_intel": missing_intel,
            "missing_ind": missing_ind,
        }
        now = self.now().isoformat()
        source = {
            "kind": "report",
            "label": f"会话提交报告《{title}》",
            "title": title,
            "filename": filename,
            "report_id": report_id,
            "uploaded_at": now,
            "coverage": coverage,
        }
        interpretation, memory = self._build_interpretation(result, source=source, gene=None)
        payload["result"] = result
        payload["interpretation"] = interpretation
        payload["memory_text"] = memory
        payload["report_override"] = {
            "title": title,
            "filename": filename,
            "report_id": report_id,
            "uploaded_at": now,
            "coverage": coverage,
        }
        payload["updated_at"] = now
        self._save(record_id, payload)

        missing_total = len(missing_intel) + len(missing_ind)
        note = (
            f"解读报告已按这份报告修正（智能 {coverage['intel']}/{len(all_intel)}、"
            f"指标 {coverage['ind']}/{len(all_ind)}）"
        )
        if missing_total:
            note += f"；缺失 {missing_total} 项沿用原测评分数"
        return {"revised": True, "note": note, "coverage": coverage}

    def _overlay_report_indicators(self, result: dict, raw_ind: dict) -> dict:
        """用报告中的 40 项指标覆盖融合结果的指标层，缺失项保持融合值。"""
        all_ind = [
            ind["id"]
            for intel in self.bank.intelligences
            for ind in intel["indicators"]
        ]
        ind_scores: dict[str, float] = {}
        for key, value in (raw_ind or {}).items():
            if key in all_ind:
                number = _score_value(value)
                if number is not None:
                    ind_scores[key] = number
        for ind_id, value in ind_scores.items():
            item = (result.get("ind") or {}).get(ind_id)
            if item is not None:
                item["score"] = value
                item["source"] = "gene-report"
        for intel in self.bank.intelligences:
            items = [
                result["ind"][ind["id"]]
                for ind in intel["indicators"]
                if ind["id"] in (result.get("ind") or {})
            ]
            for rank, item in enumerate(sorted(items, key=lambda entry: -entry["score"]), 1):
                item["rank"] = rank
        return {
            "intel": len(self.bank.intel_ids),
            "ind": len(ind_scores),
            "missing_intel": [],
            "missing_ind": [ind_id for ind_id in all_ind if ind_id not in ind_scores],
        }

    def apply_gene_report(
        self,
        scores,
        *,
        title: str = "提交基因报告",
        report_id=None,
        filename: str = "",
        path: str = "",
    ) -> dict:
        """把会话提交的基因报告写入基因分，并按融合口径重算解读报告。"""
        record_id, payload = self._load()
        raw_intel = (scores or {}).get("intel") or {}
        raw_ind = (scores or {}).get("ind") or {}
        intel_scores: dict[str, float] = {}
        for intel_id in self.bank.intel_ids:
            number = _score_value(raw_intel.get(intel_id))
            if number is not None:
                intel_scores[intel_id] = float(int(round(number)))
        if len(intel_scores) < len(self.bank.intel_ids):
            return {
                "revised": False,
                "mode": "gene",
                "note": "报告中未识别到完整的 8 项智能分，未按基因报告更新",
            }

        current_gene = payload.get("gene") or {}
        result = payload.get("result") or {}
        if (
            str(current_gene.get("report_id")) == str(report_id)
            and current_gene.get("scores") == {key: int(value) for key, value in intel_scores.items()}
            and result.get("fusion_version") != "REPORT-OVERRIDE"
            and "report_override" not in payload
        ):
            return {
                "revised": False,
                "mode": "gene",
                "note": "解读报告已是最新的基因报告结果",
            }

        gene = {
            "filename": filename or f"{title}.txt",
            "confidence": "high",
            "scores": {key: int(value) for key, value in intel_scores.items()},
            "notes": f"从会话提交报告《{title}》解析",
            "uploaded_at": self.now().isoformat(),
            "path": path,
            "report_id": report_id,
            "title": title,
        }
        payload["gene"] = gene
        if payload.get("status") != "completed" or not result:
            self._save(record_id, payload)
            return {
                "revised": False,
                "mode": "gene",
                "note": "基因分已保存，完成基础测评后即可生成解读报告",
            }

        try:
            refreshed = self._fuse_result(payload)
        except OnboardingError as exc:
            return {"revised": False, "mode": "gene", "note": str(exc)}
        coverage = self._overlay_report_indicators(refreshed, raw_ind)
        source = self._assessment_source(gene)
        interpretation, memory = self._build_interpretation(
            refreshed, source=source, gene=gene
        )
        payload["result"] = refreshed
        payload["interpretation"] = interpretation
        payload["memory_text"] = memory
        payload.pop("report_override", None)
        payload["updated_at"] = self.now().isoformat()
        self._save(record_id, payload)
        note = (
            f"解读报告已按基因报告《{title}》更新"
            f"（基因分 8 项，指标覆盖 {coverage['ind']}/{coverage['ind'] + len(coverage['missing_ind'])} 项）"
        )
        return {"revised": True, "mode": "gene", "note": note, "coverage": coverage}

