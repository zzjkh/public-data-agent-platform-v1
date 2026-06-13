from types import SimpleNamespace

import numpy as np

from app.ingestion.parsers.ocr_engine import rapidocr_result_to_blocks


def test_rapidocr_result_to_blocks_converts_polygon_and_score() -> None:
    result = SimpleNamespace(
        txts=["浙江省统计公报", ""],
        boxes=[[[1, 2], [11, 2], [11, 8], [1, 8]], [[0, 0], [1, 0], [1, 1], [0, 1]]],
        scores=[0.98, 0.5],
    )

    blocks = rapidocr_result_to_blocks(result)

    assert len(blocks) == 1
    assert blocks[0].text == "浙江省统计公报"
    assert blocks[0].bbox == (1.0, 2.0, 11.0, 8.0)
    assert blocks[0].confidence == 0.98


def test_rapidocr_result_to_blocks_supports_legacy_tuple() -> None:
    result = (
        [
            [
                [[3, 4], [13, 4], [13, 10], [3, 10]],
                "杭州市生产总值",
                0.91,
            ]
        ],
        0.2,
    )

    blocks = rapidocr_result_to_blocks(result)

    assert len(blocks) == 1
    assert blocks[0].text == "杭州市生产总值"
    assert blocks[0].bbox == (3.0, 4.0, 13.0, 10.0)
    assert blocks[0].confidence == 0.91


def test_rapidocr_result_to_blocks_accepts_numpy_arrays() -> None:
    result = SimpleNamespace(
        txts=np.array(["丽水市统计资料"]),
        boxes=np.array([[[2, 3], [12, 3], [12, 9], [2, 9]]]),
        scores=np.array([0.95]),
    )

    blocks = rapidocr_result_to_blocks(result)

    assert blocks[0].text == "丽水市统计资料"
    assert blocks[0].bbox == (2.0, 3.0, 12.0, 9.0)
