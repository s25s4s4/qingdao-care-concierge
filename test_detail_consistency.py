"""每次发布前可复跑：玩法/比分/结算/历史不可变与渲染契约。"""
import copy
import json
import os
import unittest

import rule_engine as r
import verify

DATA = os.path.join(os.path.dirname(__file__), 'data', 'official_matches.json')


class DetailConsistencyTests(unittest.TestCase):
    def test_market_results(self):
        cases = [
            ('让负/防让平', '0-2', True, '2', 'HIT'),
            ('让负', '0-2', True, '2', 'MISS'),
            ('让负', '0-3', True, '2', 'HIT'),
            ('让胜/防让平', '2-0', True, '-2', 'HIT'),
            ('让胜', '2-0', True, '-2', 'MISS'),
            ('让胜', '3-0', True, '-2', 'HIT'),
            ('主胜/防平', '1-1', False, None, 'HIT'),
            ('客胜/防平', '1-1', False, None, 'HIT'),
            ('主胜', '1-1', False, None, 'MISS'),
            ('让负', '1-1', False, None, 'PENDING'),
            ('平局/防冷', '1-0', False, None, 'MISS'),
        ]
        for tip, score, rq, rang, expected in cases:
            with self.subTest(tip=tip, score=score, rang=rang):
                self.assertEqual(r.calculate_result(tip, score, rq, rang), expected)

    def test_rq_tip_and_scores(self):
        for rang, odds in [(2, ['2.43', '4.15', '2.10']),
                           (-2, ['1.80', '4.20', '3.00']),
                           (-1, ['4.05', '3.50', '1.62'])]:
            rr = r.build({'home': '主队', 'away': '客队', 'odds': odds,
                          'is_only_rq': True, 'rang': str(rang)})
            self.assertEqual(rr['market'], 'hhad')
            self.assertNotIn('主胜', rr['tip'])
            self.assertTrue(all(r.calculate_result(rr['tip'], s, True, rang) == 'HIT'
                                for s in rr['predicted_scores']))
            self.assertTrue(all(str(min(sum(r.parse_score(s)), 7)) in rr['predicted_goals']
                                for s in rr['predicted_scores']))
            self.assertLess(rr['model']['fit_error_pp'], 5.0)

    def test_snapshot_not_rewritten(self):
        m = {'code': '测试', 'time': '10-22 04:00', 'home': '主队', 'away': '客队',
             'is_only_rq': True, 'rang': '-2', 'tip': '让胜/防让平',
             'odds': ['1.80', '4.20', '3.00'], 'result': 'HIT', 'status': '已完赛',
             'score': '4-0', 'locked': True,
             'prediction_snapshot': {'tip': '让胜/防让平', 'sha256': 'original'}}
        snap = copy.deepcopy(m['prediction_snapshot'])
        r.normalize_match(m)
        self.assertEqual(m['prediction_snapshot'], snap)
        self.assertEqual(m['tip'], '让胜/防让平')
        self.assertEqual(m['result'], 'HIT')
        self.assertFalse(r.normalize_match(m))

    def test_independent_settlement_same_rules(self):
        m = {'tip': '让胜/防让平', 'rang': '-2', 'is_only_rq': True}
        self.assertEqual(verify.settle(m, {'finished': True, 'score': '2-0'}), 'HIT')
        self.assertEqual(m['settlement']['outcome'], '让平')
        self.assertEqual(m['result'], r.calculate_result(m['tip'], '2-0', True, '-2'))

    def test_no_fake_fallback(self):
        rr = r.build({'home': '主队', 'away': '客队', 'odds': ['-', '-', '-']})
        self.assertIsNone(rr['model'])
        self.assertEqual(rr['predicted_scores'], [])
        self.assertEqual(rr['predicted_goals'], [])

    def test_real_data_contract(self):
        with open(DATA, encoding='utf-8') as f: matches = json.load(f)['matches']
        self.assertEqual(r.validate_matches(matches), [])
        for match in matches:
            with self.subTest(code=match.get('code')):
                if match.get('is_only_rq'):
                    self.assertIsNone(match.get('quant_factors'))
                self.assertNotIn('更衣室', match['dossier']['market_attitude'])
                if match.get('detail_original') and match.get('prediction_snapshot'):
                    self.assertIn('sha256', match['prediction_snapshot'])


if __name__ == '__main__':
    unittest.main()
