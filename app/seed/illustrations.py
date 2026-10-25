"""Ilustrações SVG simples das peças, usadas como fotos provisórias até a loja cadastrar as reais."""

# lateral esquerda, barra e lateral direita do corpo (comum a camisetas, camisas e casacos)
_BODY = "L175 610 Q300 625 425 610"
_SHAPES = {
    "camiseta": f"""
      <path d="M210 170 L150 192 L72 272 L124 342 L175 304 {_BODY} L425 304 L476 342 L528 272 L450 192 L390 170 Q300 236 210 170 Z" fill="{{c}}"/>
      <path d="M210 170 Q300 236 390 170" fill="none" stroke="{{d}}" stroke-width="10"/>
      <path d="M175 304 L175 360 M425 304 L425 360" stroke="{{d}}" stroke-width="4" opacity=".5"/>""",
    "polo": f"""
      <path d="M210 170 L150 192 L72 272 L124 342 L175 304 {_BODY} L425 304 L476 342 L528 272 L450 192 L390 170 L300 200 Z" fill="{{c}}"/>
      <path d="M232 160 L300 205 L272 236 L222 182 Z M368 160 L300 205 L328 236 L378 182 Z" fill="{{c}}" stroke="{{d}}" stroke-width="5"/>
      <path d="M300 205 L300 300" stroke="{{d}}" stroke-width="5"/>
      <circle cx="300" cy="238" r="6" fill="{{d}}"/><circle cx="300" cy="272" r="6" fill="{{d}}"/>""",
    "camisa": f"""
      <path d="M210 170 L150 192 L96 262 L70 572 L132 580 L175 340 {_BODY} L425 340 L468 580 L530 572 L504 262 L450 192 L390 170 L300 196 Z" fill="{{c}}"/>
      <path d="M226 158 L300 198 L262 252 L214 186 Z M374 158 L300 198 L338 252 L386 186 Z" fill="{{c}}" stroke="{{d}}" stroke-width="5"/>
      <path d="M300 198 L300 615" stroke="{{d}}" stroke-width="5"/>
      {''.join(f'<circle cx="312" cy="{y}" r="6" fill="{{d}}"/>' for y in range(270, 600, 66))}
      <path d="M215 330 L265 330 L265 380 L215 380 Z" fill="none" stroke="{{d}}" stroke-width="4"/>
      <path d="M72 545 L134 553" stroke="{{d}}" stroke-width="5"/><path d="M528 545 L466 553" stroke="{{d}}" stroke-width="5"/>""",
    "calca": """
      <path d="M188 120 L412 120 L446 650 L332 652 L300 300 L268 652 L154 650 Z" fill="{c}"/>
      <path d="M188 120 L412 120 L414 156 L186 156 Z" fill="{d}" opacity=".55"/>
      <path d="M300 156 L300 300" stroke="{d}" stroke-width="5"/>
      <path d="M196 172 Q236 214 262 172 M404 172 Q364 214 338 172" fill="none" stroke="{d}" stroke-width="5"/>
      <path d="M206 120 L206 156 M254 120 L254 156 M346 120 L346 156 M394 120 L394 156" stroke="{d}" stroke-width="4"/>""",
    "bermuda": """
      <path d="M180 200 L420 200 L456 482 L326 494 L300 340 L274 494 L144 482 Z" fill="{c}"/>
      <path d="M180 200 L420 200 L422 238 L178 238 Z" fill="{d}" opacity=".55"/>
      <path d="M300 238 L300 340" stroke="{d}" stroke-width="5"/>
      <path d="M190 254 Q232 296 262 254 M410 254 Q368 296 338 254" fill="none" stroke="{d}" stroke-width="5"/>
      <path d="M150 452 L272 464 M450 452 L328 464" stroke="{d}" stroke-width="4" opacity=".6"/>""",
    "jaqueta": f"""
      <path d="M210 160 L146 186 L94 262 L68 580 L134 588 L175 340 {_BODY} L425 340 L466 588 L532 580 L506 262 L454 186 L390 160 Z" fill="{{c}}"/>
      <path d="M220 150 L300 176 L380 150 L384 186 L300 214 L216 186 Z" fill="{{d}}" opacity=".7"/>
      <path d="M300 214 L300 615" stroke="{{d}}" stroke-width="7"/>
      <path d="M200 430 L262 430 M338 430 L400 430" stroke="{{d}}" stroke-width="6"/>
      <path d="M175 580 L425 580" stroke="{{d}}" stroke-width="10" opacity=".55"/>
      <path d="M68 556 L134 564 M532 556 L466 564" stroke="{{d}}" stroke-width="8" opacity=".55"/>""",
    "moletom": f"""
      <path d="M210 170 L146 194 L94 266 L68 580 L134 588 L175 340 {_BODY} L425 340 L466 588 L532 580 L506 266 L454 194 L390 170 Z" fill="{{c}}"/>
      <path d="M206 176 Q200 84 300 80 Q400 84 394 176 Q300 246 206 176 Z" fill="{{c}}" stroke="{{d}}" stroke-width="6"/>
      <path d="M240 172 Q300 214 360 172" fill="none" stroke="{{d}}" stroke-width="6"/>
      <path d="M282 210 L278 290 M318 210 L322 290" stroke="{{d}}" stroke-width="4"/>
      <path d="M220 450 L380 450 L400 560 L200 560 Z" fill="none" stroke="{{d}}" stroke-width="5"/>
      <path d="M175 580 L425 580" stroke="{{d}}" stroke-width="12" opacity=".5"/>""",
    "bone": """
      <path d="M150 420 Q150 250 300 240 Q450 250 450 420 Z" fill="{c}"/>
      <path d="M300 240 L300 420 M220 268 Q250 340 246 420 M380 268 Q350 340 354 420" fill="none" stroke="{d}" stroke-width="5"/>
      <path d="M150 420 Q300 400 450 420 Q520 432 560 470 Q430 480 300 452 Q200 440 150 420 Z" fill="{d}"/>
      <circle cx="300" cy="244" r="12" fill="{d}"/>""",
}


def _shade(hex_color: str, factor: float) -> str:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    if factor < 1:
        r, g, b = (int(x * factor) for x in (r, g, b))
    else:
        r, g, b = (int(x + (255 - x) * (factor - 1)) for x in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def garment_svg(kind: str, color: str, background: str = "#f2f0eb") -> str:
    r, g, b = (int(color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    is_dark = 0.299 * r + 0.587 * g + 0.114 * b < 70
    dark = _shade(color, 1.45) if is_dark else _shade(color, 0.72)  # cor dos detalhes
    shape = _SHAPES[kind].format(c=color, d=dark)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 750">
  <rect width="600" height="750" fill="{background}"/>
  <ellipse cx="300" cy="680" rx="190" ry="18" fill="#000" opacity=".07"/>
  <g transform="translate(0 20)">{shape}</g>
</svg>
"""
