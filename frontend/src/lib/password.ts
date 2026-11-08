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

  // Ensure at least one of each class
  const cryptoObj = typeof window !== 'undefined' ? window.crypto : null
  const getRandomByte = (): number => {
    if (cryptoObj?.getRandomValues) {
      const buf = new Uint8Array(1)
      cryptoObj.getRandomValues(buf)
      return buf[0]!
    }
    return Math.floor(Math.random() * 256)
  }

  const pick = (chars: string) => chars[getRandomByte() % chars.length]!

  const result = [pick(upper), pick(lower), pick(digits), pick(symbols)]
  while (result.length < length) {
    result.push(pick(all))
  }

  // Fisher-Yates shuffle
  for (let i = result.length - 1; i > 0; i--) {
    const j = getRandomByte() % (i + 1)
    const temp = result[i]!
    result[i] = result[j]!
    result[j] = temp
  }

  return result.join('')
}
