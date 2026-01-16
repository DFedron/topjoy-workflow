Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# ====== 你自己的逻辑：根据项目名做事情 ======
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

    $root = if ([string]::IsNullOrWhiteSpace($TargetPath)) {
        (Get-Location).Path
    } else {
        $TargetPath
    }

    if (-not (Test-Path $root)) {
        Append-Log "Target path not found: $root"
        [System.Windows.Forms.MessageBox]::Show("Target path not found: $root", "Error")
        return
    }
    
    $root = Join-Path $root $ProjectName
    New-Item -ItemType Directory -Path $root | Out-Null
    Append-Log "Created folder: $root"
    Set-Location $root

    $basePath = Join-Path $root "unitybase"
    if (-not (Test-Path $basePath)) {
        Append-Log "Cloning unitybase into: $basePath"
        Set-Location $root
        & git clone git@git.youle.game:minigame/unitybase.git $basePath 2>&1 | ForEach-Object {
            Append-Log $_
        }
        if ($LASTEXITCODE -ne 0) {
            Append-Log "Failed to clone unitybase."
            [System.Windows.Forms.MessageBox]::Show("Failed to clone unitybase into: $basePath", "Error")
            return
        }
        
        Set-Location $basePath
        & git checkout $ProjectName 2>&1 | ForEach-Object { Append-Log $_ }

        if ($LASTEXITCODE -ne 0) {
            Append-Log "git checkout failed."
            return
        }
    } else {
        Append-Log "Base folder exists: $basePath"
    }

    $linkPath = Join-Path $root $ProjectName
    if (Test-Path $linkPath) {
        Append-Log "Project already exists: $linkPath"
        [System.Windows.Forms.MessageBox]::Show("Project already exists: $linkPath", "Error")
        return
    }

    New-Item -ItemType Directory -Path $linkPath | Out-Null
    Append-Log "Created link folder: $linkPath"
    Set-Location $linkPath
    Append-Log "Cloning project repo into: $linkPath\GamePlay"
    & git clone "git@git.youle.game:minigame/$ProjectName.git" GamePlay 2>&1 | ForEach-Object {
        Append-Log $_
    }
    if ($LASTEXITCODE -ne 0) {
        Append-Log "Failed to clone project repo."
        [System.Windows.Forms.MessageBox]::Show("Failed to clone project repo into: $linkPath\GamePlay", "Error")
        return
    }

    $svnExe = Ensure-TortoiseSvn
    if ($null -eq $svnExe) {
        return
    }

    $gameArtPath = Join-Path $linkPath "GameArt"
    if (Test-Path $gameArtPath) {
        Append-Log "GameArt already exists: $gameArtPath"
        [System.Windows.Forms.MessageBox]::Show("GameArt already exists: $gameArtPath", "Error")
        return
    }

    Append-Log "SVN checkout: $gameArtPath"
    & $svnExe checkout "svn://svn.youle.game/minigame/$ProjectName/GameArt" $gameArtPath 2>&1 | ForEach-Object {
        Append-Log $_
    }
    if ($LASTEXITCODE -ne 0) {
        Append-Log "SVN checkout failed."
        [System.Windows.Forms.MessageBox]::Show("SVN checkout failed for: $gameArtPath", "Error")
        return
    }

    $scriptRoot = Join-Path $basePath "Assets\_Script"
    $scriptLinkPath = Join-Path $scriptRoot "GamePlay"
    $existingLink = Get-Item -LiteralPath $scriptLinkPath -ErrorAction SilentlyContinue
    if ($null -ne $existingLink) {
        if ($existingLink.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            Append-Log "Removing existing link: $scriptLinkPath"
            Remove-Item -LiteralPath $scriptLinkPath -Recurse -Force
        } else {
            Append-Log "Real directory exists, not removing: $scriptLinkPath"
            [System.Windows.Forms.MessageBox]::Show("Real directory exists at _Script\\GamePlay. Please remove it manually if you want to link.", "Error")
            return
        }
    }
    Append-Log "Creating junction: $scriptLinkPath -> $linkPath\GamePlay"
    New-Item -ItemType Junction -Path $scriptLinkPath -Target (Join-Path $linkPath "GamePlay") | Out-Null

    $assetRoot = Join-Path $basePath "Assets"
    $artLinkPath = Join-Path $assetRoot "GameArt"
    $existingArtLink = Get-Item -LiteralPath $artLinkPath -ErrorAction SilentlyContinue
    if ($null -ne $existingArtLink) {
        if ($existingArtLink.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            Append-Log "Removing existing art link: $artLinkPath"
            Remove-Item -LiteralPath $artLinkPath -Recurse -Force
        } else {
            Append-Log "Real directory exists, not removing: $artLinkPath"
            [System.Windows.Forms.MessageBox]::Show("Real directory exists at Assets\\GameArt. Please remove it manually if you want to link.", "Error")
            return
        }
    }
    Append-Log "Creating junction: $artLinkPath -> $gameArtPath"
    New-Item -ItemType Junction -Path $artLinkPath -Target $gameArtPath | Out-Null
    
    $frontendPath = Join-Path $root "frontend"
    if (Test-Path $frontendPath) {
        Append-Log "frontend already exists: $frontendPath"
        [System.Windows.Forms.MessageBox]::Show("frontend already exists: $frontendPath", "Error")
        return
    }

    Append-Log "SVN checkout: $frontendPath"
    & $svnExe checkout "svn://svn.youle.game/minigame/$ProjectName/frontend" $frontendPath 2>&1 | ForEach-Object {
        Append-Log $_
    }
    if ($LASTEXITCODE -ne 0) {
        Append-Log "SVN checkout failed."
        [System.Windows.Forms.MessageBox]::Show("SVN checkout failed for: $frontendPath", "Error")
        return
    }

    # 你想做的事情写在这里：
    # 例如：Set-Location $path; git status; 调用 Unity batchmode; 创建 junction; 等
    Set-Location $linkPath
    Append-Log "Done. base: $basePath"
    Append-Log "Done. link: $linkPath"
    [System.Windows.Forms.MessageBox]::Show("OK! base: $basePath`nlink: $linkPath", "Done")
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
