from kerui_recruit.search.query import parse_query


def test_parse_query_extracts_years_degree_location_and_qs() -> None:
    parsed = parse_query("Java 后端 5年以上 硕士 上海 QS前100")

    assert parsed.keywords == "Java 后端"
    assert parsed.filters.min_years == 5.0
    assert parsed.filters.highest_degree == "MASTER"
    assert parsed.filters.location == "上海"
    assert parsed.filters.max_qs_rank == 100


def test_parse_query_returns_empty_filters_for_plain_keywords() -> None:
    parsed = parse_query("Python 金融风控")

    assert parsed.keywords == "Python 金融风控"
    assert parsed.filters.min_years is None
    assert parsed.filters.highest_degree is None
    assert parsed.filters.location is None
    assert parsed.filters.max_qs_rank is None


def test_parse_query_maps_degree_alias_to_normalized_form() -> None:
    parsed = parse_query("数据分析 本科")

    assert parsed.filters.highest_degree == "BACHELOR"
    assert "本科" not in parsed.keywords
