<?php
// For the PRTG "HTTP Advanced" sensor.
// Requires header  X-Api-Key: secret123  (GET or POST). Page contains "Service status: RUNNING".
$key = $_SERVER['HTTP_X_API_KEY'] ?? '';
if ($key !== 'secret123') { http_response_code(401); echo "Unauthorized"; exit; }
header('Content-Type: text/plain');
echo "Service status: RUNNING\nMethod: {$_SERVER['REQUEST_METHOD']}\nTime: " . date('c') . "\n";
