<#
Отчёт по лиге Fantrax за тур и сезон (туры 1..Tour).

  .\fantrax-report.ps1 -Tour 1
  .\fantrax-report.ps1 -Tour 5 -OutFile .\tour5.md

Используются только публичные данные лиги, авторизация не нужна.
#>
param(
    [int]$Tour = 1,
    [string]$LeagueId = 'rwoc4s02mrui4mac',
    [string]$OutFile,
    [double]$SuperTop = 30
)

$ErrorActionPreference = 'Stop'
[Threading.Thread]::CurrentThread.CurrentCulture = [Globalization.CultureInfo]::InvariantCulture
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$Api = "https://www.fantrax.com/fxpa/req?leagueId=$LeagueId"
$ClientVersion = '187.0.1'
$SeasonCode = 'SEASON_926_BY_PERIOD'

function Q([string]$Method, [hashtable]$Data) {
    $body = @{
        msgs  = @(@{ method = $Method; data = $Data })
        uiv   = 3
        refUrl = "https://www.fantrax.com/fantasy/league/$LeagueId/standings"
        dt    = 'DESKTOP'; at = 'WEB'; tz = 'Europe/Moscow'; v = $ClientVersion
    } | ConvertTo-Json -Depth 6 -Compress
    for ($i = 1; $i -le 3; $i++) {
        try {
            $r = Invoke-WebRequest -Uri $Api -Method Post -ContentType 'application/json' -Body $body -UseBasicParsing
            $j = $r.Content | ConvertFrom-Json
            if ($j.pageError) { throw $j.pageError.code }
            return $j.responses[0].data
        } catch {
            if ($i -eq 3) { throw }
            Start-Sleep -Seconds 2
        }
    }
}

function Num($s) {
    if ($null -eq $s -or "$s" -eq '') { return 0.0 }
    [double]::Parse(("$s" -replace ',', ''), [Globalization.CultureInfo]::InvariantCulture)
}

function Fmt([double]$x) { $x.ToString('0.00', [Globalization.CultureInfo]::InvariantCulture) }

function PrimaryPos([string]$p) { ($p -split '[,/ ]')[0] }

$out = New-Object 'System.Collections.Generic.List[string]'
function L([string]$s = '') { $out.Add($s) }
function Tbl([string[]]$Head, $Rows) {
    L ('| ' + ($Head -join ' | ') + ' |')
    L ('|' + (($Head | ForEach-Object { '---' }) -join '|') + '|')
    foreach ($r in $Rows) { L ('| ' + ($r -join ' | ') + ' |') }
    L
}
function Top($Set, [string]$Prop, [switch]$Min) {
    $arr = @(foreach ($x in $Set) { $x })
    if ($arr.Count -eq 0) { return @() }
    $m = if ($Min) { ($arr | Measure-Object $Prop -Minimum).Minimum } else { ($arr | Measure-Object $Prop -Maximum).Maximum }
    @($arr | Where-Object { $_.$Prop -eq $m })
}

# ---------- загрузка ----------
$standings = @{}   # тур -> строки таблицы
$teamName = @{}
for ($p = 1; $p -le $Tour; $p++) {
    $d = Q 'getStandings' @{ leagueId = $LeagueId; timeframeType = 'BY_PERIOD'; period = "$p" }
    $t = $d.tableList[0]
    $h = @($t.header.cells | ForEach-Object { $_.shortName })
    $iW = $h.IndexOf('W'); $iD = $h.IndexOf('D'); $iL = $h.IndexOf('L'); $iP = $h.IndexOf('Points'); $iF = $h.IndexOf('FPtsF')
    $standings[$p] = @($t.rows | ForEach-Object {
        $tm = $_.fixedCells[1]
        $teamName[$tm.teamId] = $tm.content
        [pscustomobject]@{
            TeamId = $tm.teamId; W = (Num $_.cells[$iW].content); D = (Num $_.cells[$iD].content)
            L = (Num $_.cells[$iL].content); Pts = (Num $_.cells[$iP].content); FPts = (Num $_.cells[$iF].content)
        }
    })
    Write-Host "Тур ${p}: таблица загружена" -ForegroundColor DarkGray
}
$teamIds = @($standings[1] | ForEach-Object { $_.TeamId })

$roster = New-Object 'System.Collections.Generic.List[object]'
$ownerOf = @{}  # "тур|playerId" -> запись состава
for ($p = 1; $p -le $Tour; $p++) {
    foreach ($tid in $teamIds) {
        $d = Q 'getTeamRosterInfo' @{ leagueId = $LeagueId; teamId = $tid; period = "$p"; view = 'STATS' }
        # голы и результативные передачи берём из "Standard"-вида: в "Tracked" есть только вторые передачи (A2)
        $std = Q 'getTeamRosterInfo' @{ leagueId = $LeagueId; teamId = $tid; period = "$p"; view = 'STATS'; scoringCategoryType = '1' }
        $ga = @{}
        foreach ($tb in $std.tables) {
            $h = @($tb.header.cells | ForEach-Object { $_.shortName })
            $iG = $h.IndexOf('G'); $iA = $h.IndexOf('A')
            foreach ($row in $tb.rows) {
                if (-not $row.scorer) { continue }
                $ga[$row.scorer.scorerId] = @(
                    $(if ($iG -ge 0) { Num $row.cells[$iG].content } else { 0 }),
                    $(if ($iA -ge 0) { Num $row.cells[$iA].content } else { 0 }))
            }
        }
        foreach ($tb in $d.tables) {
            $h = @($tb.header.cells | ForEach-Object { $_.shortName })
            $iF = $h.IndexOf('FPts')
            foreach ($row in $tb.rows) {
                if (-not $row.scorer) { continue }
                $pair = $ga[$row.scorer.scorerId]
                $e = [pscustomobject]@{
                    Tour = $p; TeamId = $tid; Team = $teamName[$tid]; Id = $row.scorer.scorerId
                    Name = $row.scorer.name; Club = $row.scorer.teamShortName
                    Pos = (PrimaryPos $row.scorer.posShortNames); Active = ($row.statusId -eq '1')
                    FPts = (Num $row.cells[$iF].content)
                    G = $(if ($pair) { $pair[0] } else { 0 })
                    A = $(if ($pair) { $pair[1] } else { 0 })
                }
                $roster.Add($e)
                $ownerOf["$p|$($e.Id)"] = $e
            }
        }
    }
    Write-Host "Тур ${p}: составы загружены" -ForegroundColor DarkGray
}

$players = New-Object 'System.Collections.Generic.List[object]'
for ($p = 1; $p -le $Tour; $p++) {
    $pg = 1
    do {
        $d = Q 'getPlayerStats' @{ leagueId = $LeagueId; statusOrTeamFilter = 'ALL'; seasonOrProjection = $SeasonCode
            timeframeTypeCode = 'BY_PERIOD'; transactionPeriod = "$p"; pageNumber = "$pg" }
        $h = @($d.tableHeader.cells | ForEach-Object { $_.shortName })
        $iF = $h.IndexOf('FPts')
        foreach ($r in $d.statsTable) {
            $own = $ownerOf["$p|$($r.scorer.scorerId)"]
            $players.Add([pscustomobject]@{
                Tour = $p; Id = $r.scorer.scorerId; Name = $r.scorer.name; Club = $r.scorer.teamShortName
                Pos = (PrimaryPos $r.scorer.posShortNames); FPts = (Num $r.cells[$iF].content)
                Owner = $(if ($own) { $own.Team } else { $null }); Active = $(if ($own) { $own.Active } else { $false })
            })
        }
        $tp = $d.paginatedResultSet.totalNumPages; $pg++
    } while ($pg -le $tp)
    Write-Host "Тур ${p}: игроки загружены" -ForegroundColor DarkGray
}

function OwnerText($x) {
    if (-not $x.Owner) { 'свободный агент' }
    elseif ($x.Active) { $x.Owner }
    else { "$($x.Owner) (скамейка)" }
}

# ---------- тур ----------
$cur = @($players | Where-Object { $_.Tour -eq $Tour })
$curRoster = @($roster | Where-Object { $_.Tour -eq $Tour })
$curTeams = @($standings[$Tour] | ForEach-Object { [pscustomobject]@{ Team = $teamName[$_.TeamId]; FPts = $_.FPts } })

L "# Fantrax: отчёт по туру $Tour"
L
L "## Тур $Tour"
L
$lead = Top $curTeams FPts
$last = Top $curTeams FPts -Min
L "- 🏆 **Лидер тура:** $(($lead | ForEach-Object { "**$($_.Team)** ($(Fmt $_.FPts))" }) -join ', ')"
L "- 📉 **Нелидер тура:** $(($last | ForEach-Object { "**$($_.Team)** ($(Fmt $_.FPts))" }) -join ', ')"
L
L '### Лучшие футболисты тура (основной состав)'
L
$rows = New-Object 'System.Collections.Generic.List[object]'
$act = @($curRoster | Where-Object { $_.Active })
foreach ($b in (Top $act FPts)) { $rows.Add(@('⭐ Лучший футболист', $b.Name, $b.Pos, $b.Club, $b.Team, (Fmt $b.FPts))) }
foreach ($pos in 'G', 'D', 'M', 'F') {
    foreach ($b in (Top @($act | Where-Object { $_.Pos -eq $pos }) FPts)) {
        $rows.Add(@("Лучший $(@{G='вратарь';D='защитник';M='полузащитник';F='нападающий'}[$pos])", $b.Name, $b.Pos, $b.Club, $b.Team, (Fmt $b.FPts)))
    }
}
Tbl @('Номинация', 'Игрок', 'Поз.', 'Клуб', 'Команда', 'Очки') $rows

L '### 👑 Король скамейки'
L
$rows = New-Object 'System.Collections.Generic.List[object]'
foreach ($b in (Top @($curRoster | Where-Object { -not $_.Active }) FPts)) { $rows.Add(@($b.Name, $b.Pos, $b.Club, $b.Team, (Fmt $b.FPts))) }
Tbl @('Игрок', 'Поз.', 'Клуб', 'Команда', 'Очки') $rows

L "### 🔥 Супертопы ($SuperTop+ очков за тур)"
L
$rows = New-Object 'System.Collections.Generic.List[object]'
foreach ($x in ($cur | Where-Object { $_.FPts -ge $SuperTop } | Sort-Object @{e = 'FPts'; Descending = $true }, Name)) {
    $rows.Add(@($x.Name, $x.Pos, $x.Club, (OwnerText $x), (Fmt $x.FPts)))
}
if ($rows.Count -eq 0) { L '_Никто не набрал нужное количество очков._'; L } else { Tbl @('Игрок', 'Поз.', 'Клуб', 'Команда', 'Очки') $rows }

L '### Лучшие свободные агенты тура (не были ни в одной команде)'
L
$free = @($cur | Where-Object { -not $_.Owner })
$rows = New-Object 'System.Collections.Generic.List[object]'
foreach ($b in (Top $free FPts)) { $rows.Add(@('⭐ Лучший', $b.Name, $b.Pos, $b.Club, (Fmt $b.FPts))) }
foreach ($pos in 'G', 'D', 'M', 'F') {
    foreach ($b in (Top @($free | Where-Object { $_.Pos -eq $pos }) FPts)) {
        $rows.Add(@("Лучший $(@{G='вратарь';D='защитник';M='полузащитник';F='нападающий'}[$pos])", $b.Name, $b.Pos, $b.Club, (Fmt $b.FPts)))
    }
}
Tbl @('Номинация', 'Игрок', 'Поз.', 'Клуб', 'Очки') $rows

# ---------- сезон ----------
L "## Сезон (туры 1–$Tour)"
L

$mgr = foreach ($tid in $teamIds) {
    $s = @(1..$Tour | ForEach-Object { $standings[$_] | Where-Object { $_.TeamId -eq $tid } })
    $mine = @($roster | Where-Object { $_.TeamId -eq $tid -and $_.Active })
    $run = 0; $best = 0; $bestFrom = 0; $bestTo = 0; $from = 0
    for ($p = 1; $p -le $Tour; $p++) {
        $r = $standings[$p] | Where-Object { $_.TeamId -eq $tid }
        if ($r.W -gt 0 -and $r.L -eq 0 -and $r.D -eq 0) {
            if ($run -eq 0) { $from = $p }
            $run++
            if ($run -gt $best) { $best = $run; $bestFrom = $from; $bestTo = $p }
        } else { $run = 0 }
    }
    $g = ($mine | Measure-Object G -Sum).Sum; $a = ($mine | Measure-Object A -Sum).Sum
    [pscustomobject]@{
        TeamId = $tid; Team = $teamName[$tid]
        W = ($s | Measure-Object W -Sum).Sum; D = ($s | Measure-Object D -Sum).Sum; L = ($s | Measure-Object L -Sum).Sum
        Pts = ($s | Measure-Object Pts -Sum).Sum; FPts = ($s | Measure-Object FPts -Sum).Sum
        G = $g; A = $a; GA = $g + $a; Streak = $best; From = $bestFrom; To = $bestTo
    }
}
$mgr = @($mgr | Sort-Object @{e = 'Pts'; Descending = $true }, @{e = 'FPts'; Descending = $true })

function Rng($m) { if ($m.From -eq $m.To) { "тур $($m.From)" } else { "туры $($m.From)–$($m.To)" } }

$tourScores = @(foreach ($p in 1..$Tour) { $standings[$p] | ForEach-Object { [pscustomobject]@{ Tour = $p; Team = $teamName[$_.TeamId]; FPts = $_.FPts } } })
$rec = Top $tourScores FPts
$anti = Top $tourScores FPts -Min
$sum = Top $mgr FPts
$ga = Top $mgr GA
$strk = Top $mgr Streak
$fl = $mgr[0]

L "- 🏅 **РЕКОРД лиги (лучший результат менеджера за тур):** $(($rec | ForEach-Object { "**$($_.Team)** — $(Fmt $_.FPts), тур $($_.Tour)" }) -join '; ')"
L "- 💀 **Антирекорд (худший результат менеджера за тур):** $(($anti | ForEach-Object { "**$($_.Team)** — $(Fmt $_.FPts), тур $($_.Tour)" }) -join '; ')"
L "- 💰 **Сумма очков:** $(($sum | ForEach-Object { "**$($_.Team)** — $(Fmt $_.FPts)" }) -join ', ')"
L "- ⚽🅰 **Лучший по Г+П:** $(($ga | ForEach-Object { "**$($_.Team)** — $($_.GA) (голы $($_.G) + передачи $($_.A))" }) -join ', ')"
L "- 👑 **Лидер фентези:** **$($fl.Team)** — $($fl.Pts) очк. в турнирной таблице ($($fl.W)-$($fl.D)-$($fl.L)), сумма очков $(Fmt $fl.FPts)"
L "- 🔥 **Самый длинный винстрик:** $(($strk | ForEach-Object { "**$($_.Team)** — $($_.Streak) ($(Rng $_))" }) -join ', ')"
L

L '### Таблица менеджеров'
L
$rows = New-Object 'System.Collections.Generic.List[object]'
$i = 0
foreach ($m in $mgr) { $i++; $rows.Add(@($i, $m.Team, "$($m.W)-$($m.D)-$($m.L)", $m.Pts, (Fmt $m.FPts), $m.G, $m.A, $m.GA, $m.Streak)) }
Tbl @('#', 'Менеджер', 'В-Н-П', 'Очки', 'Сумма FPts', 'Голы', 'Пасы', 'Г+П', 'Макс. серия побед') $rows

L '### 🌟 Сборная сезона (один лучший на позицию)'
L
$rows = New-Object 'System.Collections.Generic.List[object]'
foreach ($pos in 'G', 'D', 'M', 'F') {
    foreach ($b in (@($players | Where-Object { $_.Pos -eq $pos } | Sort-Object @{e = 'FPts'; Descending = $true }, Tour, Name | Select-Object -First 1))) {
        $rows.Add(@($pos, (Fmt $b.FPts), $b.Name, $b.Club, (OwnerText $b), $b.Tour))
    }
}
Tbl @('Поз.', 'Очки', 'Игрок', 'Клуб', 'У кого', 'Тур') $rows

L '### 🔟 10 лучших выступлений игроков за сезон'
L
$rows = New-Object 'System.Collections.Generic.List[object]'
$i = 0
foreach ($x in ($players | Sort-Object @{e = 'FPts'; Descending = $true }, Name | Select-Object -First 10)) {
    $i++; $rows.Add(@($i, (Fmt $x.FPts), $x.Name, $x.Tour))
}
Tbl @('#', 'Очки', 'Игрок', 'Тур') $rows

L '### 🏆 Лучший перформанс менеджеров (лучший в каждом туре)'
L
$best = foreach ($p in 1..$Tour) { Top @($standings[$p]) FPts | ForEach-Object { [pscustomobject]@{ Tour = $p; Team = $teamName[$_.TeamId]; FPts = $_.FPts } } }
$rows = New-Object 'System.Collections.Generic.List[object]'
$i = 0
foreach ($x in ($best | Sort-Object @{e = 'FPts'; Descending = $true }, Tour)) { $i++; $rows.Add(@($i, (Fmt $x.FPts), $x.Team, $x.Tour)) }
Tbl @('#', 'Очки', 'Менеджер', 'Тур') $rows

$text = $out -join "`n"
if ($OutFile) { Set-Content -Path $OutFile -Value $text -Encoding UTF8 }
$text
