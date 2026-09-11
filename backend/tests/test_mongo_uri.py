from app.db.client import mongo_host, normalize_mongo_uri


def test_raw_at_in_password_is_encoded():
    got = normalize_mongo_uri(
        "mongodb+srv://Parveen:p@ss@123@cluster.tcdgzk8.mongodb.net/?appName=EstateLens"
    )
    assert got == (
        "mongodb+srv://Parveen:p%40ss%40123@cluster.tcdgzk8.mongodb.net/?appName=EstateLens"
    )


def test_plain_localhost_untouched():
    assert normalize_mongo_uri("mongodb://localhost:27017") == "mongodb://localhost:27017"


def test_already_encoded_is_left_alone():
    uri = "mongodb+srv://u:a%40b@cluster.mongodb.net/db"
    assert normalize_mongo_uri(uri) == uri


def test_userless_uri_untouched():
    uri = "mongodb://db1.example.com:27017,db2.example.com:27017/?replicaSet=rs0"
    assert normalize_mongo_uri(uri) == uri


def test_mongo_host_strips_credentials():
    assert mongo_host(
        "mongodb+srv://Parveen:dbuser@123@estatelens.tcdgzk8.mongodb.net/?appName=EstateLens"
    ) == "estatelens.tcdgzk8.mongodb.net"
