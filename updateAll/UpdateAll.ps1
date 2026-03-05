Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# ====== 更新逻辑：根据项目名更新仓库 ======
function Run-ProjectTask([string]$ProjectName, [string]$TargetPath, [System.Windows.Forms.TextBox]$LogBox) {
    function Append-Log([string]$Message) {
        if ($null -ne $LogBox) {
            $LogBox.AppendText($Message + [Environment]::NewLine)
            [System.Windows.Forms.Application]::DoEvents()
        }
    }

    function Get-TortoiseSvnInstallDir {
        $keys = @(
            "HKLM:\SOFTWARE\TortoiseSVN",
            "HKLM:\SOFTWARE\WOW6432Node\TortoiseSVN"
        )
        foreach ($key in $keys) {
            if (Test-Path $key) {
                $dir = (Get-ItemProperty $key -ErrorAction SilentlyContinue).Directory
                if (-not [string]::IsNullOrWhiteSpace($dir)) {
                    return $dir
                }
            }
        }
        return $null
    }

    function Ensure-TortoiseSvn {
        $installDir = Get-TortoiseSvnInstallDir
        if (-not $installDir) {
            $installerPath = Join-Path $PSScriptRoot "TortoiseSVN-setup.exe"
            if (-not (Test-Path $installerPath)) {
                Append-Log "TortoiseSVN not found. Please place installer at: $installerPath"
                [System.Windows.Forms.MessageBox]::Show("TortoiseSVN not found. Please place installer at:`n$installerPath", "Error")
                return $null
            }
            $confirm = [System.Windows.Forms.MessageBox]::Show(
                "TortoiseSVN is not installed. Install now?",
                "Confirm Install",
                [System.Windows.Forms.MessageBoxButtons]::OKCancel,
                [System.Windows.Forms.MessageBoxIcon]::Question
            )
            if ($confirm -ne [System.Windows.Forms.DialogResult]::OK) {
                Append-Log "TortoiseSVN install canceled by user."
                return $null
            }
            Append-Log "Installing TortoiseSVN: $installerPath"
            $proc = Start-Process -FilePath $installerPath -ArgumentList "/quiet /norestart" -Wait -PassThru
            if ($proc.ExitCode -ne 0) {
                Append-Log "TortoiseSVN install failed. ExitCode: $($proc.ExitCode)"
                [System.Windows.Forms.MessageBox]::Show("TortoiseSVN install failed. ExitCode: $($proc.ExitCode)", "Error")
                return $null
            }
            $installDir = Get-TortoiseSvnInstallDir
            if (-not $installDir) {
                Append-Log "TortoiseSVN install completed, but registry not found."
                [System.Windows.Forms.MessageBox]::Show("TortoiseSVN install completed, but registry not found.", "Error")
                return $null
            }
        }

        $svnExe = Join-Path $installDir "bin\svn.exe"
        if (-not (Test-Path $svnExe)) {
            Append-Log "svn.exe not found under: $installDir"
            [System.Windows.Forms.MessageBox]::Show("svn.exe not found under:`n$installDir", "Error")
            return $null
        }
        return $svnExe
    }

    $workspaceRoot = if ([string]::IsNullOrWhiteSpace($TargetPath)) {
        (Get-Location).Path
    } else {
        $TargetPath
    }

    if (-not (Test-Path $workspaceRoot)) {
        Append-Log "Target path not found: $workspaceRoot"
        [System.Windows.Forms.MessageBox]::Show("Target path not found: $workspaceRoot", "Error")
        return
    }

    $root = Join-Path $workspaceRoot $ProjectName
    if (-not (Test-Path $root)) {
        Append-Log "Project root not found: $root"
        [System.Windows.Forms.MessageBox]::Show("Project root not found:`n$root", "Error")
        return
    }

    $basePath = Join-Path $root "unitybase"
    $linkPath = Join-Path $root $ProjectName
    $gameArtPath = Join-Path $linkPath "GameArt"
    $gamePlayPrimaryPath = Join-Path $linkPath "GamePlay"
    $gamePlayFallbackPath = Join-Path $linkPath $ProjectName
    $gamePlayPath = $gamePlayPrimaryPath
    if (-not (Test-Path $gamePlayPath) -and (Test-Path $gamePlayFallbackPath)) {
        $gamePlayPath = $gamePlayFallbackPath
        Append-Log "GamePlay folder not found, fallback to: $gamePlayPath"
    }

    function Ensure-GitRepo([string]$Path, [string]$DisplayName) {
        if (-not (Test-Path $Path)) {
            Append-Log "$DisplayName path not found: $Path"
            [System.Windows.Forms.MessageBox]::Show("$DisplayName path not found:`n$Path", "Error")
            return $false
        }
        if (-not (Test-Path (Join-Path $Path ".git"))) {
            Append-Log "$DisplayName is not a git repository: $Path"
            [System.Windows.Forms.MessageBox]::Show("$DisplayName is not a git repository:`n$Path", "Error")
            return $false
        }
        return $true
    }

    function Ensure-SvnRepo([string]$Path, [string]$DisplayName) {
        if (-not (Test-Path $Path)) {
            Append-Log "$DisplayName path not found: $Path"
            [System.Windows.Forms.MessageBox]::Show("$DisplayName path not found:`n$Path", "Error")
            return $false
        }
        if (-not (Test-Path (Join-Path $Path ".svn"))) {
            Append-Log "$DisplayName is not an SVN working copy: $Path"
            [System.Windows.Forms.MessageBox]::Show("$DisplayName is not an SVN working copy:`n$Path", "Error")
            return $false
        }
        return $true
    }

    if (-not (Ensure-GitRepo $basePath "UnityBase")) { return }
    if (-not (Ensure-GitRepo $gamePlayPath "GamePlay")) { return }
    if (-not (Ensure-SvnRepo $gameArtPath "GameArt")) { return }

    $svnExe = Ensure-TortoiseSvn
    if ($null -eq $svnExe) {
        return
    }

    try {
        Append-Log "Updating UnityBase (git pull): $basePath"
        Push-Location $basePath
        & git pull 2>&1 | ForEach-Object { Append-Log $_ }
        if ($LASTEXITCODE -ne 0) {
            Append-Log "UnityBase git pull failed."
            [System.Windows.Forms.MessageBox]::Show("UnityBase git pull failed:`n$basePath", "Error")
            return
        }
    } finally {
        Pop-Location
    }

    try {
        Append-Log "Updating GamePlay (git pull): $gamePlayPath"
        Push-Location $gamePlayPath
        & git pull 2>&1 | ForEach-Object { Append-Log $_ }
        if ($LASTEXITCODE -ne 0) {
            Append-Log "GamePlay git pull failed."
            [System.Windows.Forms.MessageBox]::Show("GamePlay git pull failed:`n$gamePlayPath", "Error")
            return
        }
    } finally {
        Pop-Location
    }

    try {
        Append-Log "Updating GameArt (svn update): $gameArtPath"
        Push-Location $gameArtPath
        & $svnExe update 2>&1 | ForEach-Object { Append-Log $_ }
        if ($LASTEXITCODE -ne 0) {
            Append-Log "GameArt svn update failed."
            [System.Windows.Forms.MessageBox]::Show("GameArt svn update failed:`n$gameArtPath", "Error")
            return
        }
    } finally {
        Pop-Location
    }

    Append-Log "Update completed."
    Append-Log "UnityBase: $basePath"
    Append-Log "GamePlay: $gamePlayPath"
    Append-Log "GameArt: $gameArtPath"
    [System.Windows.Forms.MessageBox]::Show("Update completed.`nUnityBase: $basePath`nGamePlay: $gamePlayPath`nGameArt: $gameArtPath", "Done")
}

# ====== UI ======
$form = New-Object System.Windows.Forms.Form
$form.Text = "Project Tool"
$form.Size = New-Object System.Drawing.Size(560, 320)
$form.StartPosition = "CenterScreen"
$form.TopMost = $false

$pathLabel = New-Object System.Windows.Forms.Label
$pathLabel.Text = "Target Path:"
$pathLabel.AutoSize = $true
$pathLabel.Location = New-Object System.Drawing.Point(20, 60)

$pathBox = New-Object System.Windows.Forms.TextBox
$pathBox.Size = New-Object System.Drawing.Size(320, 24)
$pathBox.Location = New-Object System.Drawing.Point(120, 58)
$pathBox.Text = (Get-Location).Path

$browseButton = New-Object System.Windows.Forms.Button
$browseButton.Text = "Browse"
$browseButton.Size = New-Object System.Drawing.Size(80, 28)
$browseButton.Location = New-Object System.Drawing.Point(450, 56)

$label = New-Object System.Windows.Forms.Label
$label.Text = "Project Name:"
$label.AutoSize = $true
$label.Location = New-Object System.Drawing.Point(20, 25)

$nameBox = New-Object System.Windows.Forms.ComboBox
$nameBox.Size = New-Object System.Drawing.Size(320, 24)
$nameBox.Location = New-Object System.Drawing.Point(120, 22)
$nameBox.DropDownStyle = [System.Windows.Forms.ComboBoxStyle]::DropDown
$nameBox.Items.AddRange(@("cat", "dragonwar", "mapwar"))
$nameBox.Text = ""

$logBox = New-Object System.Windows.Forms.TextBox
$logBox.Multiline = $true
$logBox.ReadOnly = $true
$logBox.ScrollBars = [System.Windows.Forms.ScrollBars]::Vertical
$logBox.Size = New-Object System.Drawing.Size(510, 120)
$logBox.Location = New-Object System.Drawing.Point(20, 150)

$browseButton.Add_Click({
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = "Select target path"
    $dialog.SelectedPath = $pathBox.Text
    if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
        $pathBox.Text = $dialog.SelectedPath
    }
})

$okButton = New-Object System.Windows.Forms.Button
$okButton.Text = "OK"
$okButton.Size = New-Object System.Drawing.Size(80, 28)
$okButton.Location = New-Object System.Drawing.Point(120, 100)

$cancelButton = New-Object System.Windows.Forms.Button
$cancelButton.Text = "Cancel"
$cancelButton.Size = New-Object System.Drawing.Size(80, 28)
$cancelButton.Location = New-Object System.Drawing.Point(210, 100)

# 点击 OK / 回车触发
$okButton.Add_Click({
    $name = $nameBox.Text.Trim()
    if ([string]::IsNullOrWhiteSpace($name)) {
        [System.Windows.Forms.MessageBox]::Show("Please input project name.", "Warning")
        return
    }
    $logBox.Clear()
    Run-ProjectTask $name $pathBox.Text.Trim() $logBox
})

# 取消/ESC 关闭
$cancelButton.Add_Click({ $form.Close() })
$form.AcceptButton = $okButton
$form.CancelButton = $cancelButton

$form.Controls.AddRange(@(
    $label,
    $nameBox,
    $pathLabel,
    $pathBox,
    $browseButton,
    $okButton,
    $cancelButton,
    $logBox
))
[void]$form.ShowDialog()
