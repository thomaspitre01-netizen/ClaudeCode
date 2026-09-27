"""Run with: python -m unittest discover tests"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from japan_re import db, dedup, normalize as n, records, sources
from japan_re.fetch import RobotsRules

FIX = Path(__file__).with_name('fixtures')


def read(name):
    return (FIX / name).read_text(encoding='utf-8')


class NormalizeTests(unittest.TestCase):
    def test_prices(self):
        self.assertEqual(n.parse_price('４，９８０万円（税込）')[0], 49_800_000)
        self.assertEqual(n.parse_price('1億2,500万円')[0], 125_000_000)
        low, note = n.parse_price('3,980万円～4,500万円')
        self.assertEqual(low, 39_800_000)
        self.assertIn('4,500', note)
        self.assertIsNone(n.parse_price('価格未定')[0])

    def test_areas(self):
        self.assertEqual(n.parse_area('１２３．４５㎡（公簿）')[0], 123.45)
        self.assertAlmostEqual(n.parse_area('37.34坪')[0], 123.44, places=1)

    def test_era_dates(self):
        self.assertEqual(n.parse_year_month('昭和50年3月'), (1975, 3))
        self.assertEqual(n.parse_year_month('平成元年'), (1989, None))
        self.assertEqual(n.parse_year_month('1968年（昭和43年）'), (1968, None))
        self.assertEqual(n.parse_year_month('昭和初期（推定）'), (None, None))

    def test_stations(self):
        s = n.parse_stations('ＪＲ中央線「吉祥寺」歩12分 京王井の頭線「井の頭公園」歩8分')
        self.assertEqual([(x['line_en'], x['station_en'], x['walk_min']) for x in s],
                         [('JR Chuo Line', 'Kichijoji', 12), ('Keio Inokashira Line', 'Inokashira-koen', 8)])
        bus = n.parse_stations('JR横須賀線「逗子」バス10分 停歩3分')[0]
        self.assertEqual((bus['station_en'], bus['bus_min'], bus['walk_min']), ('Zushi', 10, 3))

    def test_structure_and_zoning(self):
        self.assertEqual(n.parse_structure('RC造地上3階地下1階建'), ('rc', 3, 1))
        self.assertEqual(n.parse_structure('木造平屋建'), ('wood', 1, None))
        self.assertEqual(n.parse_zoning('準工業地域')[1], 'Quasi-industrial')
        self.assertEqual(n.parse_land_rights('旧法借地権'), ('leasehold', 0))

    def test_classification(self):
        self.assertEqual(n.classify_type('detached_house', '吉祥寺 戸建', '築90年の古民家')[0], 'kominka')
        self.assertEqual(n.classify_type('detached_house', '中古戸建', '近くにマンションや店舗')[0],
                         'detached_house')
        self.assertEqual(n.classify_type('land', '古家付き土地')[0], 'land')
        self.assertEqual(n.classify_condition(None, '古家付き土地、更地渡し相談')[0], 'derelict_rebuild')
        self.assertEqual(n.classify_condition(None, '一部リフォーム済')[0], 'minor_renovation')
        self.assertEqual(n.classify_condition(None, '築45年、要リフォーム')[0], 'major_renovation')

    def test_earthquake_standard(self):
        self.assertEqual(n.earthquake_standard(1975, 3), 'old')
        self.assertEqual(n.earthquake_standard(1990, None), 'new')
        self.assertEqual(n.earthquake_standard(1981, 8), 'unknown')
        self.assertEqual(n.earthquake_standard(1979, None, '耐震基準適合証明書取得済'), 'new')

    def test_address(self):
        self.assertEqual(n.split_address('神奈川県三浦郡葉山町堀内')['municipality'], 'Hayama')
        self.assertEqual(n.split_address('東京都武蔵野市吉祥寺本町2丁目')['neighborhood_ja'], '吉祥寺本町2丁目')
        self.assertIsNone(n.split_address('大阪府大阪市北区')['municipality'])


class RobotsTests(unittest.TestCase):
    TXT = """
User-agent: Googlebot
Disallow: /

User-agent: *
Disallow: /*/ajax/
Disallow: /jj/
Allow: /jj/bukken/ichiran/
Disallow: /*.json$
Crawl-delay: 10
"""

    def test_wildcards_and_precedence(self):
        r = RobotsRules.parse(self.TXT)
        self.assertEqual(r.crawl_delay, 10)
        self.assertFalse(r.allowed('https://x.jp/kodate/ajax/list'))
        self.assertFalse(r.allowed('https://x.jp/jj/other/'))
        self.assertTrue(r.allowed('https://x.jp/jj/bukken/ichiran/JJ012FC001/?ar=030'))
        self.assertFalse(r.allowed('https://x.jp/data/a.json'))
        self.assertTrue(r.allowed('https://x.jp/data/a.json?x=1'))
        self.assertTrue(r.allowed('https://x.jp/chukoikkodate/'))

    def test_specific_group_wins(self):
        r = RobotsRules.parse('User-agent: japan-re-research\nDisallow: /private/\n\n'
                              'User-agent: *\nDisallow: /\n')
        self.assertTrue(r.allowed('https://x.jp/public'))
        self.assertFalse(r.allowed('https://x.jp/private/1'))


class SourceTests(unittest.TestCase):
    def test_policies(self):
        self.assertFalse(sources.crawlable(sources.get('homes')))
        self.assertFalse(sources.crawlable(sources.get('athome')))
        self.assertTrue(sources.crawlable(sources.get('suumo')))

    def test_suumo_list_links_and_paging(self):
        s = sources.get('suumo')
        url = 'https://suumo.jp/jj/bukken/ichiran/JJ012FC001/?ar=030&bs=021&ta=13&sc=13203'
        links = s.detail_links(read('suumo_list.html'), url)
        self.assertEqual(links, ['https://suumo.jp/chukoikkodate/tokyo/sc_musashino/nc_71234567/',
                                 'https://suumo.jp/chukoikkodate/tokyo/sc_musashino/nc_71234568/'])
        self.assertIn('pn=2', s.next_page(read('suumo_list.html'), url))

    def test_suumo_detail_record(self):
        s = sources.get('suumo')
        url = 'https://suumo.jp/chukoikkodate/tokyo/sc_musashino/nc_71234567/'
        p = s.parse_detail([(url, read('suumo_detail.html')),
                            (url + 'bukkengaiyo/', read('suumo_bukkengaiyo.html'))], 'detached_house')
        row, stations = records.build(p)
        expect = dict(price_jpy=69_800_000, land_area_m2=285.12, building_area_m2=142.3, year_built=1975,
                      month_built=3, municipality='Musashino', neighborhood_ja='吉祥寺本町2丁目',
                      layout_ja='5DK', rooms=5, structure='wood', floors_above=2,
                      zoning='Category 1 low-rise exclusive residential', building_coverage_pct=40.0,
                      floor_area_ratio_pct=80.0, road_width_m=4.0, frontage_m=12.5, land_rights='freehold',
                      is_freehold=1, occupancy='vacant', property_type='traditional_house',
                      condition='major_renovation', earthquake_standard='old', lat=35.7092,
                      source_listing_id='71234567', in_scope=1)
        for k, v in expect.items():
            self.assertEqual(row[k], v, k)
        self.assertEqual(row['agency_name'], '吉祥寺ホーム株式会社')
        self.assertIn('昭和50年築', row['description_ja'])
        self.assertEqual(stations[0]['station_en'], 'Kichijoji')
        self.assertIn('販売価格', json.loads(row['raw_fields_json']))

    def test_suumo_targets_are_browse_pages(self):
        from japan_re import areas
        from japan_re.fetch import RobotsRules
        s = sources.get('suumo')
        urls = [t.url for t in s.search_targets(areas.select('core', ['Musashino', 'Hayama']), ('detached_house', 'land'))]
        self.assertIn('https://suumo.jp/chukoikkodate/tokyo/sc_musashino/', urls)
        self.assertIn('https://suumo.jp/tochi/kanagawa/sc_miuragun/', urls)
        # the JJ012FC001 search form is disallowed for all agents
        robots = RobotsRules.parse('User-agent: *\nDisallow: /jj/bukken/ichiran/JJ012FC001/\n')
        self.assertTrue(all(robots.allowed(u.replace('https://suumo.jp', '')) for u in urls))

    def test_r_estate_td_label_table_and_condo(self):
        html = """<html><head><meta property="og:title" content="白い団地｜Ｒ不動産"></head><body><table>
            <tr><td class="td_gaiyou_title1"><span>価格</span></td><td class="td_gaiyou_content1">3,590万円</td>
                <td class="td_gaiyou_title2">所在地</td><td class="td_gaiyou_content1">藤沢市辻堂</td></tr>
            <tr><td class="td_gaiyou_title1">建物面積</td><td class="td_gaiyou_content1">71.03㎡</td>
                <td class="td_gaiyou_title2">所在階</td><td class="td_gaiyou_content1">1階</td></tr>
            <tr><td class="td_gaiyou_title1">敷地面積</td><td class="td_gaiyou_content1">2401.43㎡</td>
                <td class="td_gaiyou_title2">修繕積立金</td><td class="td_gaiyou_content1">15,260円</td></tr>
            </table></body></html>"""
        s = sources.get('real_kamakura')
        p = s.parse_detail([('https://www.realkamakuraestate.jp/estate.php?n=1', html)], 'detached_house')
        self.assertEqual(p.title, '白い団地')
        row, _ = records.build(p)
        self.assertEqual(row['price_jpy'], 35_900_000)
        self.assertEqual(row['property_type'], 'condominium')
        self.assertIsNone(row['land_area_m2'])          # the block's site, not the flat's land

    def test_ieichiba_post(self):
        html = """<html><body><h1>守谷海水浴場から近い、贅沢な広さの更地です</h1>
            <a href="/area-city/122181" class="page__address">千葉県勝浦市</a>
            <p class="page__body">218坪と贅沢な広さの土地です。</p>
            <div class="page__body-summary"><p class="page__body-overview">【物件概要】※土地のみ
場所：千葉県勝浦市守谷
土地：218坪（更地）
建物：なし
構造：
現況：更地
</p><div class="page__body-price"><div>希望価格：<span>400万円</span></div></div></div>
            <a href="/area/chiba/page/2"></a></body></html>"""
        s = sources.get('ieichiba')
        p = s.parse_detail([('https://www.ieichiba.com/project/P202600853', html)], 'detached_house')
        row, _ = records.build(p)
        self.assertEqual(row['price_jpy'], 4_000_000)
        self.assertEqual(row['property_type'], 'land')
        self.assertAlmostEqual(row['land_area_m2'], 720.7, places=0)
        self.assertEqual(p.pairs['所在地'], '千葉県勝浦市守谷')
        self.assertNotIn('構造', p.pairs)
        self.assertEqual(s.next_page(html, 'https://www.ieichiba.com/area/chiba'),
                         'https://www.ieichiba.com/area/chiba/page/2')

    def test_minisoup_matches_bs4_subset(self):
        from japan_re.sources._minisoup import BeautifulSoup
        import re as _re
        soup = BeautifulSoup('<title>T</title><dl><dt>価格<dd>1万円<dt>面積<dd>2㎡</dl>'
                             '<a rel="next nofollow" href="/p2">x</a><script>var a=1</script><p class="a b">hi</p>')
        self.assertEqual([d.get_text() for d in soup.find('dl').find_all('dd')], ['1万円', '2㎡'])
        self.assertEqual(soup.find('a', rel='next')['href'], '/p2')
        self.assertEqual(soup.title.get_text(), 'T')
        self.assertEqual(soup.find('p', class_=_re.compile('^b$')).get_text(), 'hi')
        self.assertNotIn('var a', soup.get_text(' ', strip=True))

    def test_specialist_kominka(self):
        s = sources.get('real_kamakura')
        url = 'https://www.realkamakuraestate.jp/estate.php?n=27272'
        row, stations = records.build(s.parse_detail([(url, read('real_kamakura_detail.html'))], None))
        self.assertEqual(row['property_type'], 'kominka')
        self.assertEqual(row['condition'], 'full_renovation')      # 雨漏り
        self.assertEqual(row['setback_required'], 1)
        self.assertEqual(row['rebuild_prohibited'], 0)
        self.assertEqual(row['municipality'], 'Kamakura')
        self.assertEqual(row['land_area_m2'], 412.0)
        self.assertIsNone(row['year_built'])
        self.assertEqual(stations[0]['station_en'], 'Kita-Kamakura')
        self.assertTrue(row['thumbnail_url'].endswith('main.jpg'))
        self.assertNotIn('logo', row['image_urls_json'])


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(Path(self.tmp.name) / 't.sqlite')

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def _suumo(self):
        s = sources.get('suumo')
        url = 'https://suumo.jp/chukoikkodate/tokyo/sc_musashino/nc_71234567/'
        return records.build(s.parse_detail([(url, read('suumo_detail.html')),
                                             (url + 'bukkengaiyo/', read('suumo_bukkengaiyo.html'))],
                                            'detached_house'))

    def _athome(self, name):
        from japan_re.crawl import import_files
        return import_files(self.conn, sources.get('athome'), [FIX / name], category='detached_house')

    def test_sources_synced_and_restricted_disabled(self):
        on = {r['id'] for r in self.conn.execute('SELECT id FROM sources WHERE enabled = 1')}
        self.assertIn('suumo', on)
        self.assertNotIn('homes', on)

    def test_price_history_and_events(self):
        row, st = self._suumo()
        lid, outcome = db.upsert_listing(self.conn, row, st, at='2027-01-10T00:00:00+00:00')
        self.assertEqual(outcome, 'new')
        row2 = dict(row, price_jpy=62_000_000, content_hash='changed')
        _, outcome = db.upsert_listing(self.conn, row2, st, at='2027-02-10T00:00:00+00:00')
        self.assertEqual(outcome, 'price_change')
        hist = [tuple(r) for r in self.conn.execute(
            'SELECT price_jpy, previous_price_jpy FROM price_history WHERE listing_id = ? ORDER BY id', (lid,))]
        self.assertEqual(hist, [(69_800_000, None), (62_000_000, 69_800_000)])
        v = self.conn.execute('SELECT * FROM v_properties').fetchone()
        self.assertEqual((v['price_jpy'], v['initial_price_jpy']), (62_000_000, 69_800_000))
        self.assertEqual(v['first_seen'][:10], '2027-01-10')
        self.assertEqual(v['station_walk_min'], 12)
        self.assertEqual(v['price_per_m2_land'], round(62_000_000 / 285.12))

    def test_removed_after_two_complete_runs_only(self):
        row, st = self._suumo()
        lid, _ = db.upsert_listing(self.conn, row, st)
        self.assertEqual(db.close_run(self.conn, 'suumo', False, set()), 0)          # incomplete: nothing
        self.assertEqual(db.close_run(self.conn, 'suumo', True, set(), {'Kamakura'}), 0)  # other area
        db.close_run(self.conn, 'suumo', True, set(), {'Musashino'})
        self.assertEqual(db.close_run(self.conn, 'suumo', True, set(), {'Musashino'}), 1)
        status = self.conn.execute('SELECT status FROM listings WHERE id = ?', (lid,)).fetchone()[0]
        self.assertEqual(status, 'removed')
        db.mark_seen(self.conn, row['url'], db.now())
        kinds = [r[0] for r in self.conn.execute('SELECT event_type FROM listing_events ORDER BY id')]
        self.assertEqual(kinds, ['new', 'removed', 'relisted'])

    def test_dedup_merges_same_house_not_neighbour(self):
        row, st = self._suumo()
        db.upsert_listing(self.conn, row, st)
        self._athome('athome_detail.html')
        self._athome('athome_neighbour.html')
        res = dedup.run(self.conn)
        self.assertEqual(res['listings'], 3)
        self.assertEqual(res['properties'], 2)
        props = self.conn.execute('SELECT property_id, source_count, sources FROM v_properties '
                                  'ORDER BY property_id').fetchall()
        self.assertEqual(props[0]['source_count'], 2)
        reasons = json.loads(self.conn.execute('SELECT reasons_json FROM dedup_matches').fetchone()[0])
        self.assertIn('same land 285.12 m²', reasons)

    def test_favorites_survive_merge(self):
        row, st = self._suumo()
        db.upsert_listing(self.conn, row, st)
        self._athome('athome_detail.html')
        athome_pid = self.conn.execute("SELECT property_id FROM listings WHERE source_id = 'athome'").fetchone()[0]
        self.conn.execute('INSERT INTO favorites VALUES (?,?,?)', (athome_pid, db.now(), 'garden'))
        dedup.run(self.conn)
        fav = self.conn.execute('SELECT * FROM v_properties WHERE is_favorite = 1').fetchall()
        self.assertEqual(len(fav), 1)
        self.assertEqual(fav[0]['listing_count'], 2)


class FakeClient:
    """Serves fixture pages by URL, and enforces robots the way PoliteClient does."""
    def __init__(self, pages, disallow=()):
        from japan_re.fetch import Page
        self.Page, self.pages, self.disallow = Page, pages, disallow
        self.stats = {'errors': 0}
        self.requested = []

    def get(self, url):
        from japan_re.fetch import Disallowed
        if any(d in url for d in self.disallow):
            raise Disallowed(url)
        self.requested.append(url)
        html = self.pages.get(url)
        return self.Page(url, 200 if html else 404, html or '', None)


class CrawlTests(unittest.TestCase):
    def test_crawl_end_to_end(self):
        from japan_re import areas
        from japan_re.crawl import crawl_source
        s = sources.get('suumo')
        musashino = areas.select(names=['Musashino'])
        target = s.search_targets(musashino, ('detached_house',))[0].url
        a = 'https://suumo.jp/chukoikkodate/tokyo/sc_musashino/nc_71234567/'
        client = FakeClient({target: read('suumo_list.html'), a: read('suumo_detail.html'),
                             a + 'bukkengaiyo/': read('suumo_bukkengaiyo.html')},
                            disallow=('pn=2',))
        with tempfile.TemporaryDirectory() as d:
            conn = db.connect(Path(d) / 't.sqlite')
            stats = crawl_source(conn, client, s, musashino, ('detached_house',), log=lambda *_: None)
            self.assertEqual(stats['listings_seen'], 2)
            self.assertEqual(stats['new_listings'], 1)          # the second detail page 404s
            self.assertEqual(stats['robots_blocked'], 1)        # page 2 disallowed
            self.assertFalse(stats['complete'])                 # so nothing may be marked removed
            row = conn.execute('SELECT * FROM v_properties').fetchone()
            self.assertEqual(row['zoning'], 'Category 1 low-rise exclusive residential')
            # second run: fresh listing is not re-fetched
            client.requested.clear()
            crawl_source(conn, client, s, musashino, ('detached_house',), log=lambda *_: None)
            self.assertNotIn(a, client.requested)
            conn.close()

    def test_restricted_source_refused(self):
        from japan_re.crawl import crawl_source
        with tempfile.TemporaryDirectory() as d:
            conn = db.connect(Path(d) / 't.sqlite')
            with self.assertRaises(PermissionError):
                crawl_source(conn, FakeClient({}), sources.get('homes'), [], log=lambda *_: None)
            conn.close()


class SummaryTests(unittest.TestCase):
    def test_summary_line(self):
        from japan_re.translate import summary_en
        line = summary_en({'price_jpy': 48_000_000, 'municipality': 'Kamakura', 'property_type': 'kominka',
                           'land_area_m2': 310, 'building_area_m2': 140, 'year_built': 1975,
                           'station_walk_min': 8, 'nearest_station': 'JR Yokosuka Line / Kita-Kamakura',
                           'condition': 'major_renovation'})
        self.assertEqual(line, '¥48M · Kamakura · kominka · 310 m² land · 140 m² building · built 1975 · '
                               '8 min walk (Kita-Kamakura) · ¥155k/m² land · major renovation')


if __name__ == '__main__':
    unittest.main()
