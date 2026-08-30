from django.core.files.base import ContentFile


DEMO_PROFILE_ICON_THEME = {
    "chiro": ("#f8d9dd", "#9b4b5f", "flower"),
    "mika": ("#d9ecff", "#32658f", "cafe"),
    "rina": ("#e8ddff", "#6f4ca3", "moon"),
    "yuki": ("#dff3e4", "#3f7d58", "leaf"),
    "sora": ("#dff0ff", "#2f6f9f", "sky"),
    "aoi": ("#ffe7c8", "#9a6330", "sun"),
}


def demo_profile_icon_svg(username):
    theme = DEMO_PROFILE_ICON_THEME.get(username)
    if not theme:
        return ""
    bg, fg, motif = theme
    motifs = {
        "flower": '<circle cx="32" cy="24" r="8"/><circle cx="24" cy="34" r="8"/><circle cx="40" cy="34" r="8"/><circle cx="32" cy="40" r="7"/><circle cx="32" cy="33" r="5" fill="#fff"/>',
        "cafe": '<path d="M21 29h22v8a9 9 0 0 1-9 9h-4a9 9 0 0 1-9-9v-8Z"/><path d="M43 31h4a5 5 0 0 1 0 10h-4"/><path d="M25 23c0-4 4-4 4-8M35 23c0-4 4-4 4-8" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round"/>',
        "moon": '<path d="M42 43a17 17 0 1 1-17-23 16 16 0 0 0 17 23Z"/><circle cx="44" cy="21" r="3" fill="#fff"/><circle cx="50" cy="32" r="2" fill="#fff"/>',
        "leaf": '<path d="M47 18c-16 1-27 10-28 26 17 1 27-9 28-26Z"/><path d="M21 43c8-8 15-13 25-22" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round"/>',
        "sky": '<path d="M18 40h29a7 7 0 0 0-2-13 11 11 0 0 0-21-2 8 8 0 0 0-6 15Z"/><circle cx="43" cy="20" r="6" fill="#fff"/>',
        "sun": '<circle cx="32" cy="32" r="10"/><path d="M32 13v7M32 44v7M13 32h7M44 32h7M18 18l5 5M41 41l5 5M46 18l-5 5M23 41l-5 5" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round"/>',
    }
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect width="64" height="64" rx="20" fill="{bg}"/>
<g fill="{fg}" stroke="{fg}" stroke-linejoin="round">{motifs[motif]}</g>
</svg>'''


def apply_demo_profile_icon(profile, username):
    svg = demo_profile_icon_svg(username)
    if not svg:
        if profile.icon:
            profile.icon.delete(save=False)
        return
    profile.icon.save(f"demo-{username}.svg", ContentFile(svg.encode("utf-8")), save=False)
