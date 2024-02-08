# InstallSpecificGoogleChromeAndDriver.ps1

# Download and unzip Google Chrome
Invoke-WebRequest -Uri "https://edgedl.me.gvt1.com/edgedl/chrome/chrome-for-testing/121.0.6167.85/win64/chrome-win64.zip" -OutFile "chrome.zip"
Expand-Archive -Path "chrome.zip" -DestinationPath "C:/Program Files/Google/Chrome"
Remove-Item "chrome.zip"

# Download and unzip ChromeDriver
Invoke-WebRequest -Uri "https://edgedl.me.gvt1.com/edgedl/chrome/chrome-for-testing/121.0.6167.85/win64/chromedriver-win64.zip" -OutFile "chromedriver.zip"
Expand-Archive -Path "chromedriver.zip" -DestinationPath "C:/Windows"
Remove-Item "chromedriver.zip"
