interface BrandMarkProps {
  size?: number
}

/** 双螺旋标识：心理与基因两条链在同一轴上交织。 */
export function BrandMark({ size }: BrandMarkProps) {
  return (
    <svg
      className="brand-mark"
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      aria-hidden="true"
    >
      <path d="M11 4c0 6 10 6 10 12s-10 6-10 12" />
      <path d="M21 4c0 6-10 6-10 12s10 6 10 12" />
      <path d="M12.5 9h7M12.5 15h7M12.5 21h7" opacity="0.55" />
    </svg>
  )
}
