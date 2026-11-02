import sqlite3
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import application
from browser_experiment import Experiment
from metrics import Metrics
from test_metrics import values
import test_browser_integration as fixtures


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.path = Path(self.directory.name) / 'trial.sqlite'
        self.trial = Experiment(self.path)
        self.metrics = Metrics(Path(self.directory.name) / 'metrics.prom')
        self.backend = Mock(driver=None)
        self.stack = ExitStack()
        for name, value in {'metrics': self.metrics, '_trial': self.trial, '_selenium': self.backend,
                            '_browser': None, '_playwright': None, '_active_engine': None}.items():
            self.stack.enter_context(patch.object(application, name, value))

    def tearDown(self):
        self.stack.close()
        self.trial.db.close()
        self.directory.cleanup()

    def success(self, *_args):
        self.metrics.set('netflix_workflow_last_clicked', 1)
        self.metrics.set('netflix_navigation_duration_seconds', .25)
        self.metrics.workflow_finished(True, .5)
        return 'Success', None

    def test_random_choice_once_per_email_and_no_second_engine_retry(self):
        self.backend.run.side_effect = self.success
        seen = Mock()
        with patch.object(application.random, 'choice', side_effect=['playwright', 'selenium', 'playwright']) as choice, \
             patch.object(application, 'open_link_with_browser', side_effect=self.success) as playwright:
            for _ in range(3):
                application.process_email('fixture', seen)
        self.assertEqual(choice.call_count, 3)
        self.assertEqual(seen.call_count, 3)
        self.assertEqual(playwright.call_count, 2)
        self.backend.run.assert_called_once()
        result = self.trial.report()['engines']
        self.assertEqual(result['playwright']['successes'], 2)
        self.assertEqual(result['selenium']['successes'], 1)

    def test_assignment_durable_before_mark_seen(self):
        def mark_seen():
            other = sqlite3.connect(self.path)
            self.assertEqual(other.execute('SELECT engine FROM runs').fetchone()[0], 'playwright')
            other.close()
        with patch.object(application.random, 'choice', return_value='playwright'), \
             patch.object(application, 'open_link_with_browser', side_effect=self.success):
            application.process_email('fixture', mark_seen)

    def test_storage_failure_keeps_mail_unread(self):
        seen = Mock()
        with patch.object(self.trial, 'begin', side_effect=sqlite3.OperationalError('disk full')):
            with self.assertRaises(sqlite3.OperationalError):
                application.process_email('fixture', seen)
        seen.assert_not_called()
        self.backend.run.assert_not_called()

    def test_mail_flag_failure_excluded_without_browser_action(self):
        with self.assertRaises(RuntimeError):
            application.process_email('fixture', Mock(side_effect=RuntimeError('mail error')))
        result = self.trial.report()['engines']
        self.assertEqual(sum(r['excluded'] for r in result.values()), 1)
        self.assertEqual(sum(r['completed'] for r in result.values()), 0)
        self.backend.run.assert_not_called()

    def test_failed_assigned_engine_is_not_replayed_on_other_engine(self):
        self.backend.run.return_value = ('Timeout waiting for Netflix confirmation', None)
        with patch.object(application.random, 'choice', return_value='selenium'), \
             patch.object(application, 'open_link_with_browser') as other:
            application.process_email('fixture', Mock())
        other.assert_not_called()
        result = self.trial.report()['engines']['selenium']
        self.assertEqual(result['failures'], 1)
        self.assertEqual(result['outcomes'], {'timeout': 1})

    def test_already_completed_page_does_not_claim_automated_success(self):
        with patch.object(application.random, 'choice', return_value='playwright'), \
             patch.object(application, 'open_link_with_browser', return_value=('Success', None)):
            application.process_email('fixture', Mock())
        result = self.trial.report()['engines']['playwright']
        self.assertEqual(result['excluded'], 1)
        self.assertEqual(result['successes'], 0)
        self.assertIsNone(result['success_rate'])

    def test_restart_preserves_window_and_results_and_explicitly_recovers_pending(self):
        run = self.trial.begin('selenium')
        self.trial.finish(run, 'success', 3, 2, True)
        self.trial.begin('playwright')
        reader = Experiment(self.path)
        self.assertEqual(reader.ends, self.trial.ends)
        self.assertEqual(reader.report()['engines']['playwright']['pending'], 1)
        reader.recover()
        result = reader.report()['engines']
        self.assertEqual(result['selenium']['successes'], 1)
        self.assertEqual(result['playwright']['outcomes'], {'interrupted': 1})
        self.assertEqual(result['playwright']['excluded'], 1)
        reader.db.close()
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_first_week_window_and_no_automatic_winner_switch(self):
        run = self.trial.begin('playwright')
        self.trial.finish(run, 'success', 3, 2, False)
        with patch('browser_experiment.time.time', return_value=self.trial.ends + 1):
            self.trial.begin('selenium')
            report = self.trial.report()
        self.assertTrue(report['review_due'])
        self.assertFalse(report['automatic_switch'])
        self.assertEqual(report['engines']['selenium']['assigned'], 0)
        self.assertEqual(report['engines']['playwright']['successes'], 1)

    def test_summary_separates_reliability_and_successful_warm_cold_latency(self):
        for outcome, duration, warm in [('success', 2, True), ('success', 8, False),
                                        ('timeout', 30, False), ('already_success', 1, True)]:
            self.trial.finish(self.trial.begin('selenium'), outcome, duration, 1, warm)
        result = self.trial.report()['engines']['selenium']
        self.assertAlmostEqual(result['success_rate'], 2 / 3)
        self.assertEqual(result['median_success_seconds'], 5)
        self.assertEqual(result['p95_success_seconds'], 8)
        self.assertEqual(result['warm_median_seconds'], 2)
        self.assertEqual(result['cold_median_seconds'], 8)
        self.trial.publish(self.metrics)
        exported = values(self.metrics.path)
        self.assertEqual(exported['netflix_ab_selenium_successes'], 2)
        self.assertEqual(exported['netflix_ab_playwright_assigned'], 0)

    def test_engine_switch_closes_inactive_browser(self):
        application._browser = Mock()
        with patch.object(application, 'close_browser') as close:
            application.activate_engine('selenium')
        close.assert_called_once()
        self.backend.driver = Mock()
        application.activate_engine('playwright')
        self.backend.close.assert_called_once()


class ExperimentDispatchIntegrationTests(unittest.TestCase):
    def test_real_dispatch_reuses_same_engine_and_closes_on_switch(self):
        fixtures.BrowserParityTests.setUpClass()
        fixture = fixtures.BrowserParityTests('test_authenticated_confirmation')
        fixture.setUp()
        trial = Experiment(Path(fixture.directory.name) / 'dispatch.sqlite')
        try:
            with patch.object(application, '_trial', trial), patch.object(application, '_selenium', None), \
                 patch.object(application, '_active_engine', None), \
                 patch.object(application.random, 'choice', side_effect=['playwright', 'playwright', 'selenium', 'selenium']):
                try:
                    seen = Mock()
                    for _ in range(4):
                        self.assertEqual(application.process_email(fixture.base + 'authenticated', seen)[0], 'Success')
                    self.assertEqual(seen.call_count, 4)
                    self.assertEqual(fixture.clicked['authenticated'], 4)
                    self.assertIsNone(application._browser)
                    self.assertIsNotNone(application._selenium.driver)
                    report = trial.report()['engines']
                    for engine in ('selenium', 'playwright'):
                        self.assertEqual(report[engine]['successes'], 2)
                        self.assertEqual(report[engine]['warm_successes'], 1)
                        self.assertEqual(report[engine]['cold_successes'], 1)
                finally:
                    application.close_browser()
                    if application._selenium is not None:
                        application._selenium.close()
        finally:
            trial.db.close()
            fixture.tearDown()
            fixtures.BrowserParityTests.tearDownClass()


if __name__ == '__main__':
    unittest.main()
