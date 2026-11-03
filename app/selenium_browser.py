"""The warm/eager Selenium implementation, with the same confirmation gates."""
import json
import re
import shutil
import time
from urllib.parse import urlsplit
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
        options.set_capability("goog:loggingPrefs", {"performance": "ALL", "browser": "SEVERE"})
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

        diagnostics = {"request_failures": 0, "http_errors": 0, "browser_console_errors": 0,
                       "performance_log_available": True, "browser_log_available": True}
        request_meta = {}

        def collect_diagnostics():
            try:
                entries = self.driver.get_log("performance")
            except Exception:
                entries = []
                diagnostics["performance_log_available"] = False
            for entry in entries:
                try:
                    event = json.loads(entry["message"])["message"]
                    method, params = event["method"], event["params"]
                except (KeyError, TypeError, ValueError):
                    continue
                if not isinstance(params, dict):
                    continue
                request_id = params.get("requestId")
                if method == "Network.requestWillBeSent":
                    request = params.get("request", {})
                    if not isinstance(request, dict):
                        continue
                    url = urlsplit(request.get("url", "") if isinstance(request.get("url", ""), str) else "")
                    document_url = params.get("documentURL", "")
                    current = urlsplit(document_url if isinstance(document_url, str) else "")
                    request_meta[request_id] = {
                        "resource_type": params.get("type", "unknown"),
                        "method": request.get("method") if request.get("method") in
                            ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS") else "OTHER",
                        "same_origin": (url.scheme, url.netloc) == (current.scheme, current.netloc),
                    }
                    if len(request_meta) > 256:
                        request_meta.pop(next(iter(request_meta)))
                elif method == "Network.loadingFailed":
                    error = params.get("errorText", "")
                    if not isinstance(error, str):
                        error = ""
                    meta = request_meta.pop(request_id, {})
                    if params.get("canceled") is True or error == "net::ERR_ABORTED":
                        trace("request_aborted", error_code="net::ERR_ABORTED", **meta)
                        continue
                    diagnostics["request_failures"] += 1
                    trace("request_failed", error_code=error if re.fullmatch(r"net::ERR_[A-Z_]+", error) else "unknown",
                          **meta)
                elif method == "Network.responseReceived":
                    response = params.get("response", {})
                    if not isinstance(response, dict):
                        continue
                    resource_type = params.get("type", "unknown")
                    try:
                        status = int(response.get("status", 0))
                    except (TypeError, ValueError):
                        continue
                    meta = request_meta.pop(request_id, {"resource_type": resource_type})
                    if status >= 400:
                        diagnostics["http_errors"] += 1
                        trace("http_error", status=status, **meta)
                    elif resource_type in ("XHR", "Fetch"):
                        trace("response", status=status, **meta)
            try:
                browser_logs = self.driver.get_log("browser")
            except Exception:
                browser_logs = []
                diagnostics["browser_log_available"] = False
            for entry in browser_logs:
                if isinstance(entry, dict) and entry.get("level") == "SEVERE":
                    diagnostics["browser_console_errors"] += 1
                    trace("browser_console_error")

        def finish(outcome, result, content=None):
            self.metrics.workflow_finished(outcome in ("success", "already_success"), time.monotonic() - started)
            trace("finished", outcome=outcome, **diagnostics)
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
            collect_diagnostics()
            phase = "navigation"
            navigated = time.monotonic()
            driver.get(link)
            collect_diagnostics()
            self.metrics.set("netflix_navigation_duration_seconds", time.monotonic() - navigated)
            trace("navigation_completed")
            phase = "login"
            self.metrics.set("netflix_workflow_stage", 3)
            trace("login_starting")
            if not self.login_to_netflix():
                collect_diagnostics()
                return finish("login_failed", "Netflix login failed", driver.page_source)
            collect_diagnostics()
            trace("login_completed")
            phase = "confirmation_controls"
            self.metrics.set("netflix_workflow_stage", 4)
            self.wait_any(("household", "invalid", "success"), 5)
            collect_diagnostics()
            if not self.visible("invalid") and not self.visible("success"):
                phase = "confirmation_click"
                trace("click_starting", browser_state=self.state())
                button = WebDriverWait(driver, 5).until(EC.element_to_be_clickable(CONTROLS["household"]))
                button.click()
                self.metrics.set("netflix_workflow_last_clicked", 1)
                trace("click_completed")
                phase = "confirmation_result"
                try:
                    self.wait_any(("success", "invalid"), 10)
                finally:
                    collect_diagnostics()
            if self.visible("invalid"):
                return finish("invalid_link", "This link is no longer valid", driver.page_source)
            content = driver.page_source
            succeeded = True
            return finish("success" if self.metrics.get("netflix_workflow_last_clicked") else "already_success",
                          "Success", content)
        except TimeoutException:
            collect_diagnostics()
            trace("timeout_state", browser_state=self.state())
            return finish("timeout", "Timeout waiting for Netflix confirmation")
        except Exception as exception:
            collect_diagnostics()
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
