$url = "https://www.python.org/ftp/python/3.9.0/python-3.9.0-amd64.exe"
$output = "$env:TEMP\python-3.9.0.exe"

# Download the Python installer
Invoke-WebRequest -Uri $url -OutFile $output

# Install Python silently
Start-Process -FilePath $output -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_test=0" -Wait

# Verify that Python was installed successfully
if (Test-Path -Path "$env:ProgramFiles\Python") {
    Write-Host "Python 3.9 was installed successfully."
} else {
    Write-Host "Failed to install Python 3.9."
}
