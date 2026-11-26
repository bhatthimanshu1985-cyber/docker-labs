<?php
// For the PRTG "REST Custom v2" sensor (returns PRTG JSON format).
header('Content-Type: application/json');
$load = sys_getloadavg();
$mem = file('/proc/meminfo'); $t = $a = 0;
foreach ($mem as $l) { if (strpos($l,'MemTotal')===0) $t=(int)filter_var($l,FILTER_SANITIZE_NUMBER_INT); if (strpos($l,'MemAvailable')===0) $a=(int)filter_var($l,FILTER_SANITIZE_NUMBER_INT); }
$up = (float)explode(' ', file_get_contents('/proc/uptime'))[0];
echo json_encode(["prtg" => ["result" => [
  ["channel"=>"Load 1min","value"=>round($load[0],2),"float"=>1],
  ["channel"=>"Memory used","value"=>$t? round(($t-$a)*100/$t,1):0,"unit"=>"Percent","float"=>1],
  ["channel"=>"Uptime","value"=>(int)$up,"unit"=>"TimeSeconds"],
  ["channel"=>"Requests OK","value"=>1],
], "text" => "Host " . gethostname()]]);
