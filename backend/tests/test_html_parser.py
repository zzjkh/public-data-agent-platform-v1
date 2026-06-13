from __future__ import annotations

from app.ingestion.parsers.html_parser import parse_html_document


def test_html_parser_extracts_title_hierarchy_and_table() -> None:
    html = """
    <html>
      <head><title>网页标题</title></head>
      <body>
        <nav>导航链接</nav>
        <h1>北京市公共数据开放办法</h1>
        <p>第一条 为了促进公共数据开放利用，制定本办法。</p>
        <h2>第一章 总则</h2>
        <p>第二条 本办法适用于本市行政区域内公共数据开放活动。</p>
        <table>
          <tr><th>指标</th><th>数值</th></tr>
          <tr><td>开放数据集</td><td>1200</td></tr>
        </table>
        <footer>页脚</footer>
      </body>
    </html>
    """

    parsed = parse_html_document(html, fallback_title="fallback.html")

    assert parsed.title == "北京市公共数据开放办法"
    assert "导航链接" not in parsed.clean_text
    assert "页脚" not in parsed.clean_text
    assert parsed.elements[0].element_type == "title"
    assert parsed.elements[0].heading_level == 1
    assert parsed.elements[2].heading_level == 2
    assert parsed.elements[2].parent_index == 0
    assert parsed.elements[-1].element_type == "table"
    assert "指标 | 数值" in parsed.elements[-1].content
    assert "# 北京市公共数据开放办法" in parsed.markdown_text
    assert parsed.extraction_mode == "dom"


def test_html_parser_extracts_script_embedded_statistical_table() -> None:
    html = """
    <html>
      <head><title>Document</title></head>
      <body>
        <div class="book"></div>
        <script>
          var data = {
            "templetname": "各市国民经济主要指标（2023年）",
            "fixedRowsTop": 2,
            "data": [
              ["城市", "年末常住人口（万人）", "生产总值(亿元)", ""],
              ["", "", "", "第一产业"],
              ["杭州市", "1252.2", "20059", "347"],
              ["宁波市", "969.7", "16453", "384"]
            ],
            "remark": "注：相关指标为2023年快报数据。"
          };
        </script>
      </body>
    </html>
    """

    parsed = parse_html_document(html, fallback_title="fallback.html")

    assert parsed.title == "各市国民经济主要指标（2023年）"
    assert parsed.extraction_mode == "script_json_table"
    assert len(parsed.elements) == 4
    assert parsed.elements[1].element_type == "table"
    assert "城市=杭州市" in parsed.elements[1].content
    assert "年末常住人口（万人）=1252.2" in parsed.elements[1].content
    assert "生产总值(亿元) / 第一产业=347" in parsed.elements[1].content
    assert parsed.elements[1].metadata == {
        "source": "script_json_table",
        "table_name": "各市国民经济主要指标（2023年）",
        "source_row_index": 2,
    }
    assert parsed.elements[-1].content == "注：相关指标为2023年快报数据。"
    assert "var data" not in parsed.clean_text


def test_html_parser_falls_back_when_script_data_is_not_valid_json() -> None:
    html = """
    <html>
      <head><title>普通页面</title></head>
      <body>
        <script>var data = {invalid: true};</script>
        <p>普通正文内容。</p>
      </body>
    </html>
    """

    parsed = parse_html_document(html, fallback_title="fallback.html")

    assert parsed.extraction_mode == "dom"
    assert parsed.title == "普通页面"
    assert "普通正文内容。" in parsed.clean_text
