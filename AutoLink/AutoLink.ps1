Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# ====== 你自己的逻辑：根据项目名做事情 ======
function Run-ProjectTask([string]$ProjectName, [string]$TargetPath, [string]$CodePath, [string]$GameArtPath, [System.Windows.Forms.TextBox]$LogBox) {
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

    $projectRoot = Join-Path (Split-Path -Parent $root) $ProjectName
    if (-not (Test-Path $projectRoot)) {
        Append-Log "Creating project root: $projectRoot"
        New-Item -ItemType Directory -Path $projectRoot -Force | Out-Null
    }

    if (-not (Test-Path $CodePath)) {
        Append-Log "Cloning code repo to: $CodePath"
        & git clone "git@git.youle.game:minigame/$ProjectName.git" $CodePath 2>&1 | ForEach-Object {
            Append-Log $_
        }
    }

    if (-not (Test-Path $GameArtPath)) {
        $svnExe = Ensure-TortoiseSvn
        if (-not $svnExe) {
            return
        }
        Append-Log "Checking out GameArt to: $GameArtPath"
        & $svnExe checkout "svn://svn.youle.game/minigame/$ProjectName/GameArt" $GameArtPath 2>&1 | ForEach-Object {
            Append-Log $_
        }
    }
    
    $scriptRoot = Join-Path $root "Assets\_Script"
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
    Append-Log "Creating junction: $scriptLinkPath -> $CodePath"
    New-Item -ItemType Junction -Path $scriptLinkPath -Target $CodePath | Out-Null

    $artLinkPath = Join-Path $root "Assets\GameArt"
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
    Append-Log "Creating junction: $artLinkPath -> $GameArtPath"
    New-Item -ItemType Junction -Path $artLinkPath -Target $GameArtPath | Out-Null
 
    $gitDir = Join-Path $CodePath ".git"
    if (Test-Path $gitDir) {
        Set-Location $CodePath
        & git pull 2>&1 | ForEach-Object {
            Append-Log $_
        }
    } else {
        Append-Log "Skip git pull: not a git repo: $CodePath"
    }
    
    $svnDir = Join-Path $GameArtPath ".svn"
    if (Test-Path $svnDir) {
        Set-Location $GameArtPath
        & svn update 2>&1 | ForEach-Object {
            Append-Log $_
        }
    } else {
        Append-Log "Skip svn update: not an SVN working copy: $GameArtPath"
    }
    Set-Location $root
    git stash
    git fetch
    & git checkout $ProjectName 2>&1 | ForEach-Object {
        Append-Log $_
    }
    & git pull 2>&1 | ForEach-Object {
        Append-Log $_
    }
    git stash pop
    Append-Log "Done. code: $scriptLinkPath"
    Append-Log "Done. art: $GameArtPath"
    [System.Windows.Forms.MessageBox]::Show("OK!")
}

# ====== UI ======
$form = New-Object System.Windows.Forms.Form
$form.Text = "Auto Link"
$form.Size = New-Object System.Drawing.Size(560, 400)
$form.StartPosition = "CenterScreen"
$form.TopMost = $false

$pathLabel = New-Object System.Windows.Forms.Label
$pathLabel.Text = "UnityBase Path:"
$pathLabel.AutoSize = $true
$pathLabel.Location = New-Object System.Drawing.Point(20, 60)
$pathLabel.Anchor = [System.Windows.Forms.AnchorStyles]::Top -bor [System.Windows.Forms.AnchorStyles]::Left

$pathBox = New-Object System.Windows.Forms.TextBox
$pathBox.Size = New-Object System.Drawing.Size(320, 24)
$pathBox.Location = New-Object System.Drawing.Point(120, 58)
$pathBox.Text = (Get-Location).Path
$pathBox.Anchor = [System.Windows.Forms.AnchorStyles]::Top -bor [System.Windows.Forms.AnchorStyles]::Left -bor [System.Windows.Forms.AnchorStyles]::Right

$browseButton = New-Object System.Windows.Forms.Button
$browseButton.Text = "Browse"
$browseButton.Size = New-Object System.Drawing.Size(80, 28)
$browseButton.Location = New-Object System.Drawing.Point(450, 56)
$browseButton.Anchor = [System.Windows.Forms.AnchorStyles]::Top -bor [System.Windows.Forms.AnchorStyles]::Right

$label = New-Object System.Windows.Forms.Label
$label.Text = "Project Name:"
$label.AutoSize = $true
$label.Location = New-Object System.Drawing.Point(20, 25)
$label.Anchor = [System.Windows.Forms.AnchorStyles]::Top -bor [System.Windows.Forms.AnchorStyles]::Left

$nameBox = New-Object System.Windows.Forms.ComboBox
$nameBox.Size = New-Object System.Drawing.Size(320, 24)
$nameBox.Location = New-Object System.Drawing.Point(120, 22)
$nameBox.DropDownStyle = [System.Windows.Forms.ComboBoxStyle]::DropDown
$nameBox.Items.AddRange(@("cat", "dragonwar", "mapwar", "cookingsheep", "tread"))
$nameBox.Text = ""
$nameBox.Anchor = [System.Windows.Forms.AnchorStyles]::Top -bor [System.Windows.Forms.AnchorStyles]::Left -bor [System.Windows.Forms.AnchorStyles]::Right

$codePathLabel = New-Object System.Windows.Forms.Label
$codePathLabel.Text = "Code Path:"
$codePathLabel.AutoSize = $true
$codePathLabel.Location = New-Object System.Drawing.Point(20, 95)
$codePathLabel.Anchor = [System.Windows.Forms.AnchorStyles]::Top -bor [System.Windows.Forms.AnchorStyles]::Left

$codePathBox = New-Object System.Windows.Forms.TextBox
$codePathBox.Size = New-Object System.Drawing.Size(320, 24)
$codePathBox.Location = New-Object System.Drawing.Point(120, 92)
$codePathBox.Anchor = [System.Windows.Forms.AnchorStyles]::Top -bor [System.Windows.Forms.AnchorStyles]::Left -bor [System.Windows.Forms.AnchorStyles]::Right

$codeBrowseButton = New-Object System.Windows.Forms.Button
$codeBrowseButton.Text = "Browse"
$codeBrowseButton.Size = New-Object System.Drawing.Size(80, 28)
$codeBrowseButton.Location = New-Object System.Drawing.Point(450, 90)
$codeBrowseButton.Anchor = [System.Windows.Forms.AnchorStyles]::Top -bor [System.Windows.Forms.AnchorStyles]::Right

$gameArtPathLabel = New-Object System.Windows.Forms.Label
$gameArtPathLabel.Text = "GameArt Path:"
$gameArtPathLabel.AutoSize = $true
$gameArtPathLabel.Location = New-Object System.Drawing.Point(20, 130)
$gameArtPathLabel.Anchor = [System.Windows.Forms.AnchorStyles]::Top -bor [System.Windows.Forms.AnchorStyles]::Left

$gameArtPathBox = New-Object System.Windows.Forms.TextBox
$gameArtPathBox.Size = New-Object System.Drawing.Size(320, 24)
$gameArtPathBox.Location = New-Object System.Drawing.Point(120, 127)
$gameArtPathBox.Anchor = [System.Windows.Forms.AnchorStyles]::Top -bor [System.Windows.Forms.AnchorStyles]::Left -bor [System.Windows.Forms.AnchorStyles]::Right

$gameArtBrowseButton = New-Object System.Windows.Forms.Button
$gameArtBrowseButton.Text = "Browse"
$gameArtBrowseButton.Size = New-Object System.Drawing.Size(80, 28)
$gameArtBrowseButton.Location = New-Object System.Drawing.Point(450, 125)
$gameArtBrowseButton.Anchor = [System.Windows.Forms.AnchorStyles]::Top -bor [System.Windows.Forms.AnchorStyles]::Right

$logBox = New-Object System.Windows.Forms.TextBox
$logBox.Multiline = $true
$logBox.ReadOnly = $true
$logBox.ScrollBars = [System.Windows.Forms.ScrollBars]::Vertical
$logBox.Size = New-Object System.Drawing.Size(510, 120)
$logBox.Location = New-Object System.Drawing.Point(20, 230)
$logBox.Anchor = [System.Windows.Forms.AnchorStyles]::Top -bor [System.Windows.Forms.AnchorStyles]::Bottom -bor [System.Windows.Forms.AnchorStyles]::Left -bor [System.Windows.Forms.AnchorStyles]::Right

$currentPath = (Get-Location).Path
$codePathAuto = $true
$settingCodePath = $false
$updateCodePathDefault = {
    if ($codePathAuto) {
        $settingCodePath = $true
        $codePathBox.Text = [IO.Path]::Combine($currentPath, $nameBox.Text.Trim(), $nameBox.Text.Trim())
        $settingCodePath = $false
    }
}
$codePathBox.Add_TextChanged({
    if (-not $settingCodePath) {
        $codePathAuto = $false
    }
})

$gameArtAuto = $true
$settingGameArtPath = $false
$updateGameArtDefault = {
    if ($gameArtAuto) {
        $settingGameArtPath = $true
        $gameArtDefault = [IO.Path]::Combine($currentPath, $nameBox.Text.Trim(), "GameArt")
        $gameArtPathBox.Text = $gameArtDefault
        $settingGameArtPath = $false
    }
}
$gameArtPathBox.Add_TextChanged({
    if (-not $settingGameArtPath) {
        $gameArtAuto = $false
    }
})


$baseAuto = $true
$settingBasePath = $false
$updateBaseDefault = {
    if ($baseAuto) {
        $settingBasePath = $true
        $baseDefault = [IO.Path]::Combine($currentPath, "unitybase")
        $pathBox.Text = $baseDefault
        $settingBasePath = $false
    }
}
$pathBox.Add_TextChanged({
    if (-not $settingBasePath) {
        $baseAuto = $false
    }
})

$nameBox.Add_TextChanged({
    & $updateCodePathDefault
    & $updateGameArtDefault
    & $updateBaseDefault
})
$form.Add_Shown({
    & $updateCodePathDefault
    & $updateGameArtDefault
    & $updateBaseDefault
})

$browseButton.Add_Click({
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = "Select target path"
    $dialog.SelectedPath = $pathBox.Text
    if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
        $pathBox.Text = $dialog.SelectedPath
    }
})

$codeBrowseButton.Add_Click({
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = "Select code path"
    $dialog.SelectedPath = $codePathBox.Text
    if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
        $codePathAuto = $false
        $codePathBox.Text = $dialog.SelectedPath
    }
})

$gameArtBrowseButton.Add_Click({
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = "Select GameArt path"
    $dialog.SelectedPath = $gameArtPathBox.Text
    if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
        $gameArtAuto = $false
        $gameArtPathBox.Text = $dialog.SelectedPath
    }
})

$okButton = New-Object System.Windows.Forms.Button
$okButton.Text = "OK"
$okButton.Size = New-Object System.Drawing.Size(80, 28)
$okButton.Location = New-Object System.Drawing.Point(120, 170)
$okButton.Anchor = [System.Windows.Forms.AnchorStyles]::Top -bor [System.Windows.Forms.AnchorStyles]::Left

$cancelButton = New-Object System.Windows.Forms.Button
$cancelButton.Text = "Cancel"
$cancelButton.Size = New-Object System.Drawing.Size(80, 28)
$cancelButton.Location = New-Object System.Drawing.Point(210, 170)
$cancelButton.Anchor = [System.Windows.Forms.AnchorStyles]::Top -bor [System.Windows.Forms.AnchorStyles]::Left

$autoButton = New-Object System.Windows.Forms.Button
$autoButton.Text = "Auto"
$autoButton.Size = New-Object System.Drawing.Size(80, 28)
$autoButton.Location = New-Object System.Drawing.Point(300, 170)
$autoButton.Anchor = [System.Windows.Forms.AnchorStyles]::Top -bor [System.Windows.Forms.AnchorStyles]::Left

# 点击 OK / 回车触发
$okButton.Add_Click({
    $name = $nameBox.Text.Trim()
    if ([string]::IsNullOrWhiteSpace($name)) {
        [System.Windows.Forms.MessageBox]::Show("Please input project name.", "Warning")
        return
    }
    $logBox.Clear()
    Run-ProjectTask $name $pathBox.Text.Trim() $codePathBox.Text.Trim() $gameArtPathBox.Text.Trim() $logBox
})

$autoButton.Add_Click({
    $codePathAuto = $true
    $gameArtAuto = $true
    & $updateCodePathDefault
    & $updateGameArtDefault
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
    $codePathLabel,
    $codePathBox,
    $codeBrowseButton,
    $gameArtPathLabel,
    $gameArtPathBox,
    $gameArtBrowseButton,
    $okButton,
    $autoButton,
    $cancelButton,
    $logBox
))
[void]$form.ShowDialog()
