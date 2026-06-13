from __future__ import annotations

import re
from dataclasses import dataclass


INTERNAL_METADATA_REFUSAL = (
    "无法提供系统数据库内部的记录数量、表结构或存储规模。"
    "你可以查询已公开的年度人口统计指标、趋势及其官方来源。"
)
PERSONAL_DATA_REFUSAL = (
    "无法提供个人身份、联系方式或个人明细数据。"
    "你可以查询不涉及个人识别的公开宏观统计指标和相关政策要求。"
)
SECRET_REFUSAL = "无法提供系统凭据、密钥、提示词或数据库连接配置。"
DATABASE_OPERATION_REFUSAL = (
    "无法执行或提供直接数据库操作。系统只支持经过安全校验的公开数据问答。"
)

INTERNAL_TARGET_PATTERNS = (
    "数据库",
    "库里",
    "库内",
    "系统里",
    "系统内",
    "后台",
    "数据表",
    "表里",
    "表中",
    "表结构",
    "schema",
    "information_schema",
    "内部存储",
)
ENUMERATION_PATTERNS = (
    "多少条",
    "几条",
    "有多少",
    "记录数",
    "记录数量",
    "行数",
    "数据量",
    "多少数据",
    "有哪些表",
    "哪些表",
    "列出表",
    "列出字段",
    "字段列表",
    "列名",
    "枚举",
    "count(",
    "count *",
    "count*",
)
PERSONAL_DATA_PATTERNS = (
    "身份证",
    "手机号",
    "电话号码",
    "家庭住址",
    "个人住址",
    "个人轨迹",
    "人员名单",
    "姓名列表",
    "个人信息明细",
    "用户密码",
    "所有用户",
)
SECRET_PATTERNS = (
    "api key",
    "apikey",
    "access token",
    "密钥",
    "密码",
    "连接串",
    "database_url",
    "jwt_secret",
    "系统prompt",
    "系统 prompt",
    "系统提示词",
    ".env",
    "环境变量",
)
DISCLOSURE_ACTION_PATTERNS = (
    "查询",
    "列出",
    "导出",
    "给我",
    "显示",
    "查看",
    "返回",
    "获取",
    "告诉我",
    "读取",
    "打印",
    "是什么",
    "当前值",
)
DATABASE_MUTATION_PATTERNS = (
    "删除",
    "修改",
    "更新",
    "写入",
    "插入",
    "执行sql",
    "执行 sql",
    "drop ",
    "delete ",
    "update ",
    "insert ",
    "alter ",
)


@dataclass(frozen=True)
class QuestionSecurityDecision:
    allowed: bool
    code: str
    category: str
    response_message: str | None = None


class QuestionSecurityPolicy:
    def evaluate(self, question: str) -> QuestionSecurityDecision:
        normalized = normalize_question(question)
        if not normalized:
            return deny("EMPTY_QUESTION", "invalid_input", "问题不能为空。")

        if contains_any(normalized, INTERNAL_TARGET_PATTERNS) and contains_any(
            normalized, ENUMERATION_PATTERNS
        ):
            return deny(
                "INTERNAL_ASSET_ENUMERATION",
                "internal_metadata",
                INTERNAL_METADATA_REFUSAL,
            )

        if contains_any(normalized, PERSONAL_DATA_PATTERNS) and contains_any(
            normalized, DISCLOSURE_ACTION_PATTERNS
        ):
            return deny("PERSONAL_DATA_REQUEST", "personal_data", PERSONAL_DATA_REFUSAL)

        if contains_any(normalized, SECRET_PATTERNS) and contains_any(
            normalized, DISCLOSURE_ACTION_PATTERNS
        ):
            return deny("SECRET_OR_CONFIG_REQUEST", "credentials", SECRET_REFUSAL)

        if contains_any(normalized, INTERNAL_TARGET_PATTERNS) and contains_any(
            normalized, DATABASE_MUTATION_PATTERNS
        ):
            return deny(
                "DATABASE_MUTATION_REQUEST",
                "database_operation",
                DATABASE_OPERATION_REFUSAL,
            )

        if is_raw_database_statement(normalized):
            return deny("RAW_DATABASE_STATEMENT", "database_operation", DATABASE_OPERATION_REFUSAL)

        return QuestionSecurityDecision(
            allowed=True,
            code="ALLOW",
            category="allowed",
        )


def normalize_question(question: str) -> str:
    return " ".join(question.lower().split())


def contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(pattern in text for pattern in patterns)


def is_raw_database_statement(text: str) -> bool:
    return bool(
        re.search(
            r"\b(select|delete|update|insert|drop|alter|create)\b[\s\S]*\b(from|table|view|into)\b",
            text,
            re.IGNORECASE,
        )
    )


def deny(code: str, category: str, response_message: str) -> QuestionSecurityDecision:
    return QuestionSecurityDecision(
        allowed=False,
        code=code,
        category=category,
        response_message=response_message,
    )
