/**
 * 浏览器原生语音识别封装(Web Speech API)。
 *
 * 识别能力由浏览器提供:Chrome 等实现会把音频发送到厂商服务,可能需要联网;
 * 本模块不录音、不落盘、不保存任何语音数据,只把转写文本交给调用方。
 */

import { useCallback, useEffect, useRef, useState } from 'react'

export interface SpeechRecognitionResultLike {
  readonly isFinal: boolean
  readonly length: number
  [index: number]: { readonly transcript: string }
}

export interface SpeechRecognitionEventLike {
  readonly resultIndex: number
  readonly results: {
    readonly length: number
    [index: number]: SpeechRecognitionResultLike
  }
}

export interface SpeechRecognitionErrorLike {
  readonly error: string
}

export interface SpeechRecognitionLike {
  lang: string
  continuous: boolean
  interimResults: boolean
  onresult: ((event: SpeechRecognitionEventLike) => void) | null
  onerror: ((event: SpeechRecognitionErrorLike) => void) | null
  onend: (() => void) | null
  start(): void
  stop(): void
  abort(): void
}

interface SpeechRecognitionCtor {
  new (): SpeechRecognitionLike
}

const ERROR_MESSAGES: Record<string, string> = {
  'not-allowed': '麦克风权限被拒绝,请点击「打开设置」允许后重试',
  'service-not-allowed': '麦克风权限被拒绝,请点击「打开设置」允许后重试',
  'audio-capture': '未检测到麦克风',
  network: '语音识别需要联网,请检查网络后重试',
  'no-speech': '没有听到声音,请再试一次',
}

interface UseSpeechRecognitionOptions {
  lang?: string
  /** 回调累计转写文本(包含已确定段落与当前临时段落),final 为真的表示全部段落已确定。 */
  onTranscript: (transcript: string, final: boolean) => void
  /** 回调可读提示与原始错误码,便于调用方按错误类型提供下一步操作。 */
  onError?: (message: string, code: string) => void
}

export interface SpeechRecognitionController {
  supported: boolean
  listening: boolean
  start: () => void
  stop: () => void
}

/** 读取浏览器提供的构造函数;不支持时返回 null,不抛错。 */
export function getSpeechRecognitionCtor(): SpeechRecognitionCtor | null {
  if (typeof window === 'undefined') return null
  const scope = window as unknown as {
    SpeechRecognition?: SpeechRecognitionCtor
    webkitSpeechRecognition?: SpeechRecognitionCtor
  }
  return scope.SpeechRecognition ?? scope.webkitSpeechRecognition ?? null
}

function describeError(code: string): string {
  return ERROR_MESSAGES[code] ?? '语音识别失败,请重试'
}

/** 拼接本次识别会话的全部段落;任意一段未确定时 final 为假。 */
function collectTranscript(event: SpeechRecognitionEventLike): { text: string; final: boolean } {
  let text = ''
  let final = true
  for (let index = 0; index < event.results.length; index += 1) {
    const result = event.results[index]
    text += result[0]?.transcript ?? ''
    if (!result.isFinal) final = false
  }
  return { text, final }
}

export function useSpeechRecognition(
  options: UseSpeechRecognitionOptions,
): SpeechRecognitionController {
  const { lang = 'zh-CN', onTranscript, onError } = options
  const supported = useRef(getSpeechRecognitionCtor() !== null).current
  const [listening, setListening] = useState(false)
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null)
  // 通过 ref 转发最新回调,避免父组件重渲染导致识别实例频繁重建。
  const callbacksRef = useRef({ onTranscript, onError })

  useEffect(() => {
    callbacksRef.current = { onTranscript, onError }
  }, [onTranscript, onError])

  const stop = useCallback(() => {
    const recognition = recognitionRef.current
    recognitionRef.current = null
    setListening(false)
    if (!recognition) return
    try {
      recognition.stop()
    } catch {
      // 识别可能已自行结束,忽略停止异常。
    }
  }, [])

  const start = useCallback(() => {
    if (recognitionRef.current) return
    const Ctor = getSpeechRecognitionCtor()
    if (!Ctor) return

    const recognition = new Ctor()
    recognition.lang = lang
    recognition.continuous = true
    recognition.interimResults = true
    recognition.onresult = (event) => {
      const { text, final } = collectTranscript(event)
      if (text) callbacksRef.current.onTranscript(text, final)
    }
    recognition.onerror = (event) => {
      callbacksRef.current.onError?.(describeError(event.error), event.error)
    }
    recognition.onend = () => {
      if (recognitionRef.current === recognition) recognitionRef.current = null
      setListening(false)
    }

    recognitionRef.current = recognition
    setListening(true)
    try {
      recognition.start()
    } catch {
      recognitionRef.current = null
      setListening(false)
      callbacksRef.current.onError?.('语音识别启动失败,请重试', 'start-failed')
    }
  }, [lang])

  useEffect(
    () => () => {
      const recognition = recognitionRef.current
      recognitionRef.current = null
      if (!recognition) return
      try {
        recognition.abort()
      } catch {
        // 组件卸载时的清理异常无需处理。
      }
    },
    [],
  )

  return { supported, listening, start, stop }
}
