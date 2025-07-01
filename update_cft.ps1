<#
.SYNOPSIS
    Downloads and extracts the latest stable version of Chrome for Testing and ChromeDriver.
.DESCRIPTION
    This script fetches the latest version information from the official Google Chrome Labs JSON endpoint.
    It then downloads the win64 versions of both Chrome for Testing and ChromeDriver,
    extracts them into a specified directory, and cleans up the downloaded zip files.
.PARAMETER DestinationPath
    The folder where Chrome and ChromeDriver will be installed.
    Defaults to "C:\Program Files\ChromeForTesting".
.EXAMPLE
    .\update-chrome.ps1
    Downloads and installs to "C:\Program Files\ChromeForTesting".
.EXAMPLE
    .\update-chrome.ps1 -DestinationPath "C:\MyTools\Chrome"
    Downloads and installs to the specified custom path.
#>
param(
    [string]$DestinationPath = "C:\Program Files\ChromeForTesting"
)

$ErrorActionPreference = 'Stop'
$jsonUrl = "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json"
$tempDir = $env:TEMP

Write-Host "Checking for destination directory: $DestinationPath"
if (-not (Test-Path -Path $DestinationPath)) {
    Write-Host "Creating destination directory..."
    New-Item -ItemType Directory -Path $DestinationPath -Force | Out-Null
}

try {
    Write-Host "Fetching latest version information from $jsonUrl"
    $versionsData = Invoke-RestMethod -Uri $jsonUrl

    # Get download URLs for win64
    $chromeUrl = ($versionsData.channels.Stable.downloads.chrome | Where-Object { $_.platform -eq 'win64' }).url
    $driverUrl = ($versionsData.channels.Stable.downloads.chromedriver | Where-Object { $_.platform -eq 'win64' }).url

    if (-not $chromeUrl -or -not $driverUrl) {
        Write-Error "Could not find download URLs for win64 platform."
        exit 1
    }

    $chromeZipPath = Join-Path $tempDir "chrome-win64.zip"
    $driverZipPath = Join-Path $tempDir "chromedriver-win64.zip"

    # Download Chrome
    Write-Host "Downloading Chrome for Testing from: $chromeUrl"
    Invoke-WebRequest -Uri $chromeUrl -OutFile $chromeZipPath
    Write-Host "Chrome downloaded to $chromeZipPath"

    # Download ChromeDriver
    Write-Host "Downloading ChromeDriver from: $driverUrl"
    Invoke-WebRequest -Uri $driverUrl -OutFile $driverZipPath
    Write-Host "ChromeDriver downloaded to $driverZipPath"

    # Extract archives
    Write-Host "Extracting Chrome to $DestinationPath..."
    Expand-Archive -Path $chromeZipPath -DestinationPath $DestinationPath -Force
    
    Write-Host "Extracting ChromeDriver to $DestinationPath..."
    Expand-Archive -Path $driverZipPath -DestinationPath $DestinationPath -Force

    # The executables are inside subfolders, e.g., 'chrome-win64' and 'chromedriver-win64'
    # You might want to move them or add the subfolders to your PATH.
    $chromeExePath = Join-Path $DestinationPath "chrome-win64\chrome.exe"
    $driverExePath = Join-Path $DestinationPath "chromedriver-win64\chromedriver.exe"

    Write-Host "---"
    Write-Host "Update complete."
    Write-Host "Chrome for Testing executable: $chromeExePath"
    Write-Host "ChromeDriver executable: $driverExePath"
    Write-Host "Consider adding the relevant subdirectories to your system's PATH environment variable."

}
catch {
    Write-Error "An error occurred: $_"
    exit 1
}
finally {
    # Clean up downloaded zip files
    if (Test-Path $chromeZipPath) {
        Write-Host "Cleaning up $chromeZipPath..."
        Remove-Item $chromeZipPath -Force
    }
    if (Test-Path $driverZipPath) {
        Write-Host "Cleaning up $driverZipPath..."
        Remove-Item $driverZipPath -Force
    }
}