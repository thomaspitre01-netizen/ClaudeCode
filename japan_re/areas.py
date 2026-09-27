"""Target geography: Greater Tokyo and Greater Kamakura, nothing else yet.

Each municipality carries its JIS code (what SUUMO's search takes as `sc=`) and the
romaji slug the portals use in their URLs. `tier` says how deep to go:

  core       the areas named in the brief (Chuo Line corridor, Kamakura/Zushi/Hayama)
  tokyo      the rest of the Tokyo agglomeration inside the metropolis
  fringe     neighbouring cities that fit the same lifestyle; off unless --tier fringe

Everything outside this table is marked out of scope when it is stored.
"""
from __future__ import annotations

from dataclasses import dataclass

PRICE_CAP_JPY = 150_000_000


@dataclass(frozen=True)
class Municipality:
    code: str          # JIS X 0402 city code
    pref: str          # Tokyo | Kanagawa
    name_ja: str
    name_en: str
    slug: str          # portal URL slug, e.g. 'musashino-city'
    tier: str


def _m(code, pref, ja, en, slug, tier):
    return Municipality(code, pref, ja, en, slug, tier)


MUNICIPALITIES: list[Municipality] = [
    # --- core: Chuo Line corridor and western Tokyo ---
    _m('13114', 'Tokyo', '中野区', 'Nakano', 'nakano-ku', 'core'),
    _m('13115', 'Tokyo', '杉並区', 'Suginami', 'suginami-ku', 'core'),     # SUUMO: Koenji station pages only (see portals.py)
    _m('13203', 'Tokyo', '武蔵野市', 'Musashino', 'musashino-city', 'core'),  # Kichijoji, Mitaka stn north
    _m('13204', 'Tokyo', '三鷹市', 'Mitaka', 'mitaka-city', 'core'),
    _m('13210', 'Tokyo', '小金井市', 'Koganei', 'koganei-city', 'core'),
    _m('13214', 'Tokyo', '国分寺市', 'Kokubunji', 'kokubunji-city', 'core'),
    _m('13215', 'Tokyo', '国立市', 'Kunitachi', 'kunitachi-city', 'core'),
    _m('13229', 'Tokyo', '西東京市', 'Nishitokyo', 'nishitokyo-city', 'core'),
    _m('13208', 'Tokyo', '調布市', 'Chofu', 'chofu-city', 'core'),
    _m('13112', 'Tokyo', '世田谷区', 'Setagaya', 'setagaya-ku', 'core'),
    _m('13120', 'Tokyo', '練馬区', 'Nerima', 'nerima-ku', 'core'),
    # --- core: Greater Kamakura ---
    _m('14204', 'Kanagawa', '鎌倉市', 'Kamakura', 'kamakura-city', 'core'),  # incl. Kita-Kamakura, Ofuna
    _m('14208', 'Kanagawa', '逗子市', 'Zushi', 'zushi-city', 'fringe'),   # dropped from core 27 Sep 2026 (Thomas)
    _m('14301', 'Kanagawa', '葉山町', 'Hayama', 'hayama-town', 'fringe'),
    # --- tokyo: rest of the 23 wards ---
    _m('13101', 'Tokyo', '千代田区', 'Chiyoda', 'chiyoda-ku', 'tokyo'),
    _m('13102', 'Tokyo', '中央区', 'Chuo', 'chuo-ku', 'tokyo'),
    _m('13103', 'Tokyo', '港区', 'Minato', 'minato-ku', 'tokyo'),
    _m('13104', 'Tokyo', '新宿区', 'Shinjuku', 'shinjuku-ku', 'tokyo'),
    _m('13105', 'Tokyo', '文京区', 'Bunkyo', 'bunkyo-ku', 'tokyo'),
    _m('13106', 'Tokyo', '台東区', 'Taito', 'taito-ku', 'tokyo'),
    _m('13107', 'Tokyo', '墨田区', 'Sumida', 'sumida-ku', 'tokyo'),
    _m('13108', 'Tokyo', '江東区', 'Koto', 'koto-ku', 'tokyo'),
    _m('13109', 'Tokyo', '品川区', 'Shinagawa', 'shinagawa-ku', 'tokyo'),
    _m('13110', 'Tokyo', '目黒区', 'Meguro', 'meguro-ku', 'tokyo'),
    _m('13111', 'Tokyo', '大田区', 'Ota', 'ota-ku', 'tokyo'),
    _m('13113', 'Tokyo', '渋谷区', 'Shibuya', 'shibuya-ku', 'tokyo'),
    _m('13116', 'Tokyo', '豊島区', 'Toshima', 'toshima-ku', 'tokyo'),
    _m('13117', 'Tokyo', '北区', 'Kita', 'kita-ku', 'tokyo'),
    _m('13118', 'Tokyo', '荒川区', 'Arakawa', 'arakawa-ku', 'tokyo'),
    _m('13119', 'Tokyo', '板橋区', 'Itabashi', 'itabashi-ku', 'tokyo'),
    _m('13121', 'Tokyo', '足立区', 'Adachi', 'adachi-ku', 'tokyo'),
    _m('13122', 'Tokyo', '葛飾区', 'Katsushika', 'katsushika-ku', 'tokyo'),
    _m('13123', 'Tokyo', '江戸川区', 'Edogawa', 'edogawa-ku', 'tokyo'),
    # --- tokyo: Tama area ---
    _m('13201', 'Tokyo', '八王子市', 'Hachioji', 'hachioji-city', 'tokyo'),
    _m('13202', 'Tokyo', '立川市', 'Tachikawa', 'tachikawa-city', 'tokyo'),
    _m('13205', 'Tokyo', '青梅市', 'Ome', 'ome-city', 'tokyo'),
    _m('13206', 'Tokyo', '府中市', 'Fuchu', 'fuchu-city', 'tokyo'),
    _m('13207', 'Tokyo', '昭島市', 'Akishima', 'akishima-city', 'tokyo'),
    _m('13209', 'Tokyo', '町田市', 'Machida', 'machida-city', 'tokyo'),
    _m('13211', 'Tokyo', '小平市', 'Kodaira', 'kodaira-city', 'tokyo'),
    _m('13212', 'Tokyo', '日野市', 'Hino', 'hino-city', 'tokyo'),
    _m('13213', 'Tokyo', '東村山市', 'Higashimurayama', 'higashimurayama-city', 'tokyo'),
    _m('13218', 'Tokyo', '福生市', 'Fussa', 'fussa-city', 'tokyo'),
    _m('13219', 'Tokyo', '狛江市', 'Komae', 'komae-city', 'tokyo'),
    _m('13220', 'Tokyo', '東大和市', 'Higashiyamato', 'higashiyamato-city', 'tokyo'),
    _m('13221', 'Tokyo', '清瀬市', 'Kiyose', 'kiyose-city', 'tokyo'),
    _m('13222', 'Tokyo', '東久留米市', 'Higashikurume', 'higashikurume-city', 'tokyo'),
    _m('13223', 'Tokyo', '武蔵村山市', 'Musashimurayama', 'musashimurayama-city', 'tokyo'),
    _m('13224', 'Tokyo', '多摩市', 'Tama', 'tama-city', 'tokyo'),
    _m('13225', 'Tokyo', '稲城市', 'Inagi', 'inagi-city', 'tokyo'),
    _m('13227', 'Tokyo', '羽村市', 'Hamura', 'hamura-city', 'tokyo'),
    _m('13228', 'Tokyo', 'あきる野市', 'Akiruno', 'akiruno-city', 'tokyo'),
    # --- fringe: same lifestyle, just outside the two cores ---
    _m('14205', 'Kanagawa', '藤沢市', 'Fujisawa', 'fujisawa-city', 'fringe'),   # Enoshima, Katase
    _m('14201', 'Kanagawa', '横須賀市', 'Yokosuka', 'yokosuka-city', 'fringe'),  # Akiya, Sajima (west coast)
    _m('14110', 'Kanagawa', '横浜市栄区', 'Yokohama Sakae', 'yokohamashisakae-ku', 'fringe'),
    _m('14108', 'Kanagawa', '横浜市金沢区', 'Yokohama Kanazawa', 'yokohamashikanazawa-ku', 'fringe'),
    _m('14130', 'Kanagawa', '川崎市', 'Kawasaki', 'kawasaki-city', 'fringe'),
]

TIERS = ('core', 'tokyo', 'fringe')
PREF_JA = {'Tokyo': '東京都', 'Kanagawa': '神奈川県'}
PREF_CODE = {'Tokyo': '13', 'Kanagawa': '14'}

_BY_JA = {m.name_ja: m for m in MUNICIPALITIES}


def select(tiers: str | list[str] = 'core', names: list[str] | None = None) -> list[Municipality]:
    """Municipalities for a crawl. `tiers='tokyo'` means core+tokyo; 'fringe' means all."""
    if names:
        wanted = {n.lower() for n in names}
        return [m for m in MUNICIPALITIES
                if m.name_en.lower() in wanted or m.name_ja in names or m.code in names]
    if isinstance(tiers, str):
        tiers = list(TIERS[:TIERS.index(tiers) + 1])
    return [m for m in MUNICIPALITIES if m.tier in tiers]


def match_address(address_ja: str | None) -> tuple[Municipality | None, str | None]:
    """Find the municipality in a Japanese address and return what follows it.

    '東京都武蔵野市吉祥寺本町2丁目' -> (Musashino, '吉祥寺本町2丁目')
    Handles Kawasaki/Yokohama wards ('川崎市中原区...') and the 三浦郡 prefix on Hayama.
    """
    if not address_ja:
        return None, None
    a = address_ja.replace('三浦郡', '').replace(' ', '').replace('　', '')
    for pj in PREF_JA.values():
        if a.startswith(pj):
            a = a[len(pj):]
    # Longest name first, so 横浜市栄区 wins over a bare 横浜市.
    for name in sorted(_BY_JA, key=len, reverse=True):
        idx = a.find(name)
        if idx != -1 and idx <= 1:
            rest = a[idx + len(name):]
            if name == '川崎市':
                rest = rest.split('区', 1)[-1] if '区' in rest[:4] else rest
            return _BY_JA[name], rest or None
    return None, None
