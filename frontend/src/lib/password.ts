/** 0 (empty) .. 4 (strong) */
export function passwordStrength(pw: string): number {
  if (!pw) return 0
  let score = 0
  if (pw.length >= 8) score++
  if (pw.length >= 12) score++
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score++
  if (/\d/.test(pw) && /[^A-Za-z0-9]/.test(pw)) score++
  return Math.max(1, score)
}

export function generatePassword(length = 16): string {
  const upper = 'ABCDEFGHJKLMNPQRSTUVWXYZ'
  const lower = 'abcdefghijkmnopqrstuvwxyz'
  const digits = '23456789'
  const symbols = '!@#$%^&*()-_=+'
  const all = upper + lower + digits + symbols

  // Uniform integer in [0, n) from the CSPRNG, rejection sampling avoids modulo bias.
  const randomBelow = (n: number): number => {
    const limit = Math.floor(0x1_0000_0000 / n) * n
    const buf = new Uint32Array(1)
    do {
      crypto.getRandomValues(buf)
    } while (buf[0]! >= limit)
    return buf[0]! % n
  }

  const pick = (chars: string) => chars[randomBelow(chars.length)]!

  const result = [pick(upper), pick(lower), pick(digits), pick(symbols)]
  while (result.length < length) {
    result.push(pick(all))
  }

  // Fisher-Yates shuffle
  for (let i = result.length - 1; i > 0; i--) {
    const j = randomBelow(i + 1)
    const temp = result[i]!
    result[i] = result[j]!
    result[j] = temp
  }

  return result.join('')
}
