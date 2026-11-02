"""The warm/eager Selenium implementation, with the same confirmation gates."""
import re
import shutil
import time
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

CONTROLS = {
    "login": (By.CSS_SELECTOR, 'input[name="userLoginId"]'),
    "password": (By.CSS_SELECTOR, 'input[name="password"]'),
    "toggle": (By.CSS_SELECTOR, 'button[data-uia="login-toggle-button"]'),
    "continue": (By.CSS_SELECTOR, 'button[data-uia="continue-button"]'),
    "household": (By.CSS_SELECTOR, 'button[data-uia="set-primary-location-action"]'),
    "invalid": (By.XPATH, '//h1[normalize-space(.)="This link is no longer valid"]'),
    "success": (By.XPATH, '//h1[normalize-space(.)="You’ve updated your Netflix Household"]'),
    "code": (By.XPATH, '//h1[normalize-space(.)="Enter the code we sent to your email"]'),
}


class SeleniumBrowser:
    def __init__(self, metrics, logger, login, password, state_script):
        self.metrics, self.logger = metrics, logger
        self.login, self.password, self.state_script = login, password, state_script
        self.driver = None

    def close(self):
        driver, self.driver = self.driver, None
        self.metrics.set("netflix_browser_warm", 0)
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                self.logger.warning("Selenium browser cleanup failed")

    def get_browser(self):
        if self.driver is not None:
            try:
                if self.driver.window_handles:
                    return self.driver
                self.close()
            except Exception:
                self.close()
        started = time.monotonic()
        options = webdriver.ChromeOptions()
        options.page_load_strategy = "eager"
        options.binary_location = shutil.which("chromium") or shutil.which("google-chrome") or ""
        for argument in ("--headless", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"):
            options.add_argument(argument)
        for attempt in range(2):
            service = Service(shutil.which("chromedriver"))
            try:
                self.driver = webdriver.Chrome(options=options, service=service)
                self.driver.set_page_load_timeout(30)
                self.driver.set_script_timeout(30)
                break
            except Exception as exception:
                service.stop()
                self.close()
                if attempt or not isinstance(exception, WebDriverException):
                    self.metrics.update(netflix_browser_available=0,
                                        netflix_browser_last_start_timestamp_seconds=time.time())
                    self.metrics.increment("netflix_browser_start_failure_total")
                    raise
                self.logger.warning("Selenium browser startup failed; retrying once")
                time.sleep(2)
        self.metrics.update(netflix_browser_warm=1, netflix_browser_available=1,
                            netflix_browser_start_duration_seconds=time.monotonic() - started,
                            netflix_browser_last_start_timestamp_seconds=time.time())
        self.metrics.increment("netflix_browser_start_success_total")
        return self.driver

    def visible(self, name):
        return next((element for element in self.driver.find_elements(*CONTROLS[name])
                     if element.is_displayed()), None)

    def wait_any(self, names, timeout):
        return WebDriverWait(self.driver, timeout).until(
            lambda _driver: next((name for name in names if self.visible(name)), False))

    def login_to_netflix(self):
        if not self.login or not self.password:
            return False
        try:
            terminal = ("household", "invalid", "success", "code")
            self.wait_any(("login", "toggle") + terminal, 10)
            if self.visible("code"):
                return False
            if any(self.visible(name) for name in terminal[:3]):
                return True
            if not self.visible("login"):
                self.visible("toggle").click()
                self.wait_any(("login",), 10)
            if not self.visible("password") and self.visible("continue"):
                return False
            self.wait_any(("password",), 10)
            self.visible("login").send_keys(self.login)
            self.visible("password").send_keys(self.password)
            self.visible("password").send_keys(Keys.RETURN)
            self.wait_any(terminal, 10)
            return not self.visible("code")
        except TimeoutException:
            return False

    def state(self):
        try:
            return self.driver.execute_script("return (" + self.state_script + ")()")
        except Exception:
            return {"snapshot_unavailable": True}

    def run(self, body, run_id):
        started = time.monotonic()
        phase = "input"
        succeeded = False
        self.metrics.set("netflix_workflow_last_clicked", 0)

        def trace(event, **fields):
            self.logger.info("Netflix browser trace", extra={"run_id": run_id, "engine": "selenium",
                "event": event, "phase": phase, "elapsed_seconds": round(time.monotonic() - started, 6), **fields})

        def finish(outcome, result, content=None):
            self.metrics.workflow_finished(outcome in ("success", "already_success"), time.monotonic() - started)
            trace("finished", outcome=outcome)
            return result, content

        trace("started", warm_browser_present=self.driver is not None)
        try:
            if not body:
                return finish("empty_body", "Empty email body")
            link = next((url for url in re.findall(r'https?://\S+', body)
                         if "update-primary-location" in url), None)
            if link is None:
                return finish("link_not_found", "Netflix update link not found")
            phase = "browser_start"
            self.metrics.set("netflix_workflow_stage", 2)
            driver = self.get_browser()
            trace("browser_ready")
            phase = "navigation"
            navigated = time.monotonic()
            driver.get(link)
            self.metrics.set("netflix_navigation_duration_seconds", time.monotonic() - navigated)
            trace("navigation_completed")
            phase = "login"
            self.metrics.set("netflix_workflow_stage", 3)
            trace("login_starting")
            if not self.login_to_netflix():
                return finish("login_failed", "Netflix login failed", driver.page_source)
            trace("login_completed")
            phase = "confirmation_controls"
            self.metrics.set("netflix_workflow_stage", 4)
            self.wait_any(("household", "invalid", "success"), 5)
            if not self.visible("invalid") and not self.visible("success"):
                phase = "confirmation_click"
                trace("click_starting", browser_state=self.state())
                button = WebDriverWait(driver, 5).until(EC.element_to_be_clickable(CONTROLS["household"]))
                button.click()
                self.metrics.set("netflix_workflow_last_clicked", 1)
                trace("click_completed")
                phase = "confirmation_result"
                self.wait_any(("success", "invalid"), 10)
            if self.visible("invalid"):
                return finish("invalid_link", "This link is no longer valid", driver.page_source)
            content = driver.page_source
            succeeded = True
            return finish("success" if self.metrics.get("netflix_workflow_last_clicked") else "already_success",
                          "Success", content)
        except TimeoutException:
            trace("timeout_state", browser_state=self.state())
            return finish("timeout", "Timeout waiting for Netflix confirmation")
        except Exception as exception:
            trace("browser_error", error_type=type(exception).__name__)
            return finish("browser_error", "Browser workflow failed: " + type(exception).__name__)
        finally:
            if succeeded:
                try:
                    self.driver.get("about:blank")
                except Exception:
                    self.close()
            else:
                self.close()
