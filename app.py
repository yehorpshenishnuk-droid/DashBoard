<?php
function sendRequest($url) {
    $ch = curl_init();
    curl_setopt($ch, CURLOPT_URL, $url);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    return json_decode(curl_exec($ch), true);
}

$token = '687409:4164553abf6a031302898da7800b59fb';
$dateFrom = '2024-07-01';
$dateTo = '2024-09-01';
$perPage = 100;
$page = 1;

$totalCheYan = 0;
$totalPide = 0;

do {
    $url = "https://joinposter.com/api/transactions.getTransactions"
        . "?token=$token"
        . "&date_from=$dateFrom"
        . "&date_to=$dateTo"
        . "&per_page=$perPage"
        . "&page=$page";

    $data = sendRequest($url);
    if (!isset($data['response']['data'])) break;

    foreach ($data['response']['data'] as $transaction) {
        if (!isset($transaction['products'])) continue;
        foreach ($transaction['products'] as $product) {
            $name = $product['product_name'] ?? '';
            $qty = (int)$product['num'];

            if (stripos($name, 'чебурек') !== false || stripos($name, 'янтик') !== false) {
                $totalCheYan += $qty;
            } elseif (stripos($name, 'пиде') !== false || stripos($name, 'піде') !== false) {
                $totalPide += $qty;
            }
        }
    }

    $page++;
} while (count($data['response']['data']) === $perPage);

echo "Чебуреки и Янтики: $totalCheYan шт\n";
echo "Піде: $totalPide шт\n";
