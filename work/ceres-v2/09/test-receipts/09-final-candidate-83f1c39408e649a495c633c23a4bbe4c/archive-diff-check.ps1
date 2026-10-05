Add-Type -AssemblyName System.IO.Compression.FileSystem
$ErrorActionPreference='Stop'
$root=(Get-Location).Path
$archive=Join-Path $root 'work\ceres-v2-release-e290536e49c64bc2a9ffde4352869893\source-inputs.zip'
$oldArchive=Join-Path $root 'work\ceres-v2-release-87405f2e538741dabcae80b496c14865\source-inputs.zip'
$manifest=Join-Path $root 'Ceres\work\ceres-v2\09\source-inputs.json'
$run=Join-Path $root 'work\ceres-v2-test-env\09-final-candidate-83f1c39408e649a495c633c23a4bbe4c'
function Get-EntrySha($entry) { $s=$entry.Open(); try { $h=[Security.Cryptography.SHA256]::Create(); try { return ([BitConverter]::ToString($h.ComputeHash($s))).Replace('-','').ToLower() } finally { $h.Dispose() } } finally { $s.Dispose() } }
$start=(Get-Date).ToUniversalTime().ToString('o')
$new=[IO.Compression.ZipFile]::OpenRead($archive); $old=[IO.Compression.ZipFile]::OpenRead($oldArchive)
$newMap=@{}; foreach($e in $new.Entries){if(-not $e.FullName.EndsWith('/')){$newMap[$e.FullName]=[pscustomobject]@{length=$e.Length;sha=(Get-EntrySha $e)}}}
$oldMap=@{}; foreach($e in $old.Entries){if(-not $e.FullName.EndsWith('/')){$oldMap[$e.FullName]=[pscustomobject]@{length=$e.Length;sha=(Get-EntrySha $e)}}}
$added=@($newMap.Keys | Where-Object {-not $oldMap.ContainsKey($_)}); $removed=@($oldMap.Keys | Where-Object {-not $newMap.ContainsKey($_)})
$changed=@(foreach($p in $newMap.Keys){if($oldMap.ContainsKey($p) -and $newMap[$p].sha -ne $oldMap[$p].sha){$p}})
$m=Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json
$fileRows=@(foreach($p in $m.files.PSObject.Properties){[pscustomobject]@{path=$p.Name;sha=$p.Value}})
$manifestUnmatched=@($fileRows | Where-Object {-not $newMap.ContainsKey($_.path)} | ForEach-Object {$_.path})
$manifestHashMismatch=@(foreach($row in $fileRows){if($newMap.ContainsKey($row.path) -and $newMap[$row.path].sha -ne $row.sha){$row.path}})
$new.Dispose(); $old.Dispose()
$hash=(Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLower()
$onlyAdded=($added.Count -eq 1 -and [string]$added[0] -ceq 'frontend/.figma/make/site.json' -and $removed.Count -eq 0 -and $changed.Count -eq 0)
$pass=($hash -eq 'c1c286f30f029040e199dcb2d8caf670b671aaa82ee1e41fc605f49c3d522eab' -and $onlyAdded -and $fileRows.Count -eq 412 -and $newMap.Count -eq 412 -and $manifestUnmatched.Count -eq 0 -and $manifestHashMismatch.Count -eq 0)
$o=[ordered]@{startUtc=$start;endUtc=(Get-Date).ToUniversalTime().ToString('o');archiveSha256=$hash;expectedSha256='c1c286f30f029040e199dcb2d8caf670b671aaa82ee1e41fc605f49c3d522eab';archiveFiles=$newMap.Count;oldArchiveFiles=$oldMap.Count;manifestFiles=$fileRows.Count;added=$added;removed=$removed;changed=$changed;onlySiteJsonAdded=$onlyAdded;manifestMissing=$manifestUnmatched;manifestHashMismatch=$manifestHashMismatch;siteJsonSha256=$newMap['frontend/.figma/make/site.json'].sha;pass=$pass}
$json=$o | ConvertTo-Json -Depth 8
Set-Content -LiteralPath (Join-Path $run 'archive-diff.json') -Value $json -Encoding utf8
Write-Output $json
if(-not $pass){exit 5}



