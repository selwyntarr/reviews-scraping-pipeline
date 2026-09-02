from pipeline.normalize import norm_housenumber, norm_name, norm_phone, norm_street, norm_zip


def test_name_apostrophes_and_case_agree_across_sources():
    assert (
        norm_name("McSORLEY'S OLD ALE HOUSE")
        == norm_name("McSorley’s Old Ale House")
        == "mcsorleys old ale house"
    )


def test_name_strips_corporate_noise():
    assert norm_name("Acosta Restaurant") == norm_name("ACOSTA") == "acosta"
    assert norm_name("Time Out Market (Manhattan) LLC") == "time out market manhattan"


def test_street_styles_converge():
    assert norm_street("WEST   23 STREET") == norm_street("West 23rd Street") == "w 23 st"
    assert norm_street("1 AVENUE") == norm_street("1st Avenue") == "1 ave"
    assert norm_street("PARK AVENUE SOUTH") == "park ave s"


def test_phone_formats():
    assert norm_phone("+1-212-741-3560") == norm_phone("2127413560") == "2127413560"
    assert norm_phone("212-741") == ""


def test_housenumber_and_zip():
    assert norm_housenumber("411b") == "411b"
    assert norm_housenumber("34-36") == "34-36"
    assert norm_zip("10019-1234") == "10019"
    assert norm_zip("") == ""
