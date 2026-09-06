// Generates the PWA icon set from public/logo.svg.
// Re-run via `npm run icons:pwa` whenever the logo changes.
import sharp from 'sharp'
import { fileURLToPath } from 'node:url'

const publicDir = fileURLToPath(new URL('../public/', import.meta.url))
const logo = `${publicDir}logo.svg`

// Background colour baked into logo.svg.
const BACKGROUND = '#240091'

// The SVG is 160x160; density 72 renders it 1:1, so scale density to
// rasterize directly at the target size instead of resizing afterwards.
const render = (size) =>
  sharp(logo, { density: (size / 160) * 72 }).resize(size, size)

// "any" purpose icons: the logo fills the square (background is baked in).
for (const size of [192, 512]) {
  await render(size).png().toFile(`${publicDir}pwa-${size}x${size}.png`)
}

// iOS home-screen icon (iOS applies no mask of its own).
await render(180).png().toFile(`${publicDir}apple-touch-icon-180x180.png`)

// "maskable" icon: platforms crop it to circles/squircles, so keep the logo
// inside the 80% safe zone (70% content, 15% padding per side).
const maskable = 512
const padding = Math.round(maskable * 0.15)
const content = maskable - padding * 2
await render(content)
  .extend({
    top: padding,
    bottom: padding,
    left: padding,
    right: padding,
    background: BACKGROUND,
  })
  .png()
  .toFile(`${publicDir}maskable-icon-512x512.png`)
