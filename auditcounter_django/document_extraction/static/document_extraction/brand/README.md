# AuditCounter application identity

The application retains the Modern Minimalist concept from the [approved Canva reference](https://www.canva.com/design/DAHZAg-4exQ/FWOUd3No3wf6RLLLGyAgkA/edit). That reference is historical; it has not been edited as part of the application rebrand.

## Logo

The new geometric A has an open counter and an aligned accent block: a compact reference to checking business records. The SVG source uses filled geometry on a 32-unit grid, with no embedded raster image, external font, or script.

| Asset | Use |
| --- | --- |
| `auditcounter-symbol.svg` | Transparent charcoal/cobalt symbol for light surfaces |
| `auditcounter-symbol-dark.svg` | Transparent light symbol for dark surfaces |
| `auditcounter-symbol.png` / `auditcounter-symbol-dark.png` | 512 × 512 transparent raster exports |
| `auditcounter-favicon.svg` | Browser icon with a charcoal tile; readable in either browser theme |
| `auditcounter-favicon-16.png` / `auditcounter-favicon-32.png` | Small raster favicons |
| `auditcounter-apple-touch-icon.png` | 180 × 180 home-screen icon |
| `auditcounter-app-icon.png` | 512 × 512 application icon |

The application lockup uses the symbol beside live **AuditCounter** text in bundled Inter 600. Its shared template is `document_extraction/includes/brand.html`. Live text keeps the full name accessible and crisp at browser zoom levels. Do not abbreviate the name or stretch the symbol.

The SVG viewbox includes four units of clear space around the visible mark. Preserve it. Use the symbol at 24–32 CSS pixels in application navigation; use the dedicated tile at 16 pixels for favicons. The desktop wordmark is 20 px, with an 18 px treatment only on the narrowest mobile screens.

## Preserved foundations

| Role | Light | Dark |
| --- | --- | --- |
| Brand primary | `#252629` | `#252629` |
| Brand secondary | `#45556C` | `#45556C` |
| Brand accent | `#3658D4` | `#3658D4` |
| Page | `#F7F7F2` | `#141517` |
| Surface | `#FFFFFF` | `#212327` |
| Primary text | `#202124` | `#F5F5F0` |
| Secondary text | `#585D66` | `#BBBEB8` |
| Action | `#3658D4` | `#A9BAFF` |

`tokens.css` remains the source for the complete semantic palette, spacing and typography. Inter is bundled under the existing `Inter-OFL.txt` license. `approved-canva-symbol.png` is the superseded historical asset; the application no longer references it.

The mark is newly drawn for this rebrand. Originality and trademark clearance have not been established.
