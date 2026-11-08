// Applies the saved (or system) colour theme before first paint.
// Kept as an external file so the strict Content-Security-Policy (script-src 'self') allows it.
try {
  var t = localStorage.getItem('heracles.theme')
  if (t === 'dark' || ((!t || t === 'system') && matchMedia('(prefers-color-scheme: dark)').matches))
    document.documentElement.classList.add('dark')
} catch (e) {}
