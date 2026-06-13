from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.db.models.dataset import Metric, MetricValue, OpenDataset, OpenDatasetField


class OpenDatasetRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, dataset_id: UUID) -> OpenDataset | None:
        return self.db.get(OpenDataset, dataset_id)

    def get_by_name_source_url(self, *, name: str, source_url: str | None) -> OpenDataset | None:
        statement = select(OpenDataset).where(OpenDataset.name == name)
        if source_url is None:
            statement = statement.where(OpenDataset.source_url.is_(None))
        else:
            statement = statement.where(OpenDataset.source_url == source_url)
        return self.db.scalar(statement)

    def list(
        self,
        *,
        page: int,
        page_size: int,
        keyword: str | None = None,
        category: str | None = None,
        department: str | None = None,
        status: str | None = None,
    ) -> tuple[list[OpenDataset], int]:
        statement = select(OpenDataset)
        statement = self._apply_filters(
            statement,
            keyword=keyword,
            category=category,
            department=department,
            status=status,
        )

        count_statement = select(func.count(OpenDataset.id))
        count_statement = self._apply_filters(
            count_statement,
            keyword=keyword,
            category=category,
            department=department,
            status=status,
        )
        total = self.db.scalar(count_statement) or 0

        items = list(
            self.db.scalars(
                statement.order_by(OpenDataset.update_date.desc().nullslast(), OpenDataset.name.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return items, total

    def upsert_dataset(self, values: dict) -> tuple[OpenDataset, bool]:
        dataset = self.get_by_name_source_url(name=values["name"], source_url=values.get("source_url"))
        created = dataset is None
        if dataset is None:
            dataset = OpenDataset(**values)
            self.db.add(dataset)
        else:
            for key, value in values.items():
                setattr(dataset, key, value)
            dataset.updated_at = datetime.now(UTC)
        self.db.flush()
        return dataset, created

    def list_fields(self, *, dataset_id: UUID) -> list[OpenDatasetField]:
        return list(
            self.db.scalars(
                select(OpenDatasetField)
                .where(OpenDatasetField.dataset_id == dataset_id)
                .order_by(OpenDatasetField.field_name.asc())
            )
        )

    def get_field_by_name(self, *, dataset_id: UUID, field_name: str) -> OpenDatasetField | None:
        return self.db.scalar(
            select(OpenDatasetField).where(
                OpenDatasetField.dataset_id == dataset_id,
                OpenDatasetField.field_name == field_name,
            )
        )

    def upsert_field(self, values: dict) -> tuple[OpenDatasetField, bool]:
        field = self.get_field_by_name(
            dataset_id=values["dataset_id"],
            field_name=values["field_name"],
        )
        created = field is None
        if field is None:
            field = OpenDatasetField(**values)
            self.db.add(field)
        else:
            for key, value in values.items():
                setattr(field, key, value)
            field.updated_at = datetime.now(UTC)
        self.db.flush()
        return field, created

    def _apply_filters(
        self,
        statement: Select,
        *,
        keyword: str | None,
        category: str | None,
        department: str | None,
        status: str | None,
    ) -> Select:
        if keyword:
            like_keyword = f"%{keyword}%"
            statement = statement.where(
                or_(
                    OpenDataset.name.ilike(like_keyword),
                    OpenDataset.description.ilike(like_keyword),
                    OpenDataset.category.ilike(like_keyword),
                    OpenDataset.department.ilike(like_keyword),
                )
            )
        if category:
            statement = statement.where(OpenDataset.category == category)
        if department:
            statement = statement.where(OpenDataset.department == department)
        if status:
            statement = statement.where(OpenDataset.status == status)
        return statement


class MetricRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, metric_id: UUID) -> Metric | None:
        return self.db.get(Metric, metric_id)

    def get_by_indicator_code(self, indicator_code: str) -> Metric | None:
        return self.db.scalar(select(Metric).where(Metric.indicator_code == indicator_code))

    def list(
        self,
        *,
        page: int,
        page_size: int,
        keyword: str | None = None,
        domain: str | None = None,
    ) -> tuple[list[Metric], int]:
        statement = select(Metric)
        statement = self._apply_metric_filters(statement, keyword=keyword, domain=domain)
        count_statement = select(func.count(Metric.id))
        count_statement = self._apply_metric_filters(count_statement, keyword=keyword, domain=domain)
        total = self.db.scalar(count_statement) or 0
        items = list(
            self.db.scalars(
                statement.order_by(Metric.domain.asc(), Metric.indicator_code.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return items, total

    def upsert_metric(self, values: dict) -> tuple[Metric, bool]:
        metric = self.get_by_indicator_code(values["indicator_code"])
        created = metric is None
        if metric is None:
            metric = Metric(**values)
            self.db.add(metric)
        else:
            for key, value in values.items():
                setattr(metric, key, value)
            metric.updated_at = datetime.now(UTC)
        self.db.flush()
        return metric, created

    def list_values(
        self,
        *,
        metric_id: UUID,
        region_name: str | None = None,
        stat_year_from: int | None = None,
        stat_year_to: int | None = None,
    ) -> list[MetricValue]:
        statement = select(MetricValue).where(MetricValue.metric_id == metric_id)
        if region_name:
            statement = statement.where(MetricValue.region_name == region_name)
        if stat_year_from is not None:
            statement = statement.where(MetricValue.stat_year >= stat_year_from)
        if stat_year_to is not None:
            statement = statement.where(MetricValue.stat_year <= stat_year_to)
        return list(
            self.db.scalars(
                statement.order_by(
                    MetricValue.region_name.asc(),
                    MetricValue.stat_year.asc().nullslast(),
                    MetricValue.stat_month.asc().nullslast(),
                )
            )
        )

    def get_value_by_identity(
        self,
        *,
        metric_id: UUID,
        region_name: str,
        stat_period: str,
        stat_year: int | None,
        stat_month: int | None,
        data_version: str,
    ) -> MetricValue | None:
        return self.db.scalar(
            select(MetricValue).where(
                MetricValue.metric_id == metric_id,
                MetricValue.region_name == region_name,
                MetricValue.stat_period == stat_period,
                MetricValue.stat_year == stat_year,
                MetricValue.stat_month == stat_month,
                MetricValue.data_version == data_version,
            )
        )

    def upsert_value(self, values: dict) -> tuple[MetricValue, bool]:
        metric_value = self.get_value_by_identity(
            metric_id=values["metric_id"],
            region_name=values["region_name"],
            stat_period=values["stat_period"],
            stat_year=values.get("stat_year"),
            stat_month=values.get("stat_month"),
            data_version=values["data_version"],
        )
        created = metric_value is None
        if metric_value is None:
            metric_value = MetricValue(**values)
            self.db.add(metric_value)
        else:
            for key, value in values.items():
                setattr(metric_value, key, value)
        self.db.flush()
        return metric_value, created

    def _apply_metric_filters(self, statement: Select, *, keyword: str | None, domain: str | None) -> Select:
        if keyword:
            like_keyword = f"%{keyword}%"
            statement = statement.where(
                or_(
                    Metric.indicator_code.ilike(like_keyword),
                    Metric.indicator_name.ilike(like_keyword),
                    Metric.description.ilike(like_keyword),
                )
            )
        if domain:
            statement = statement.where(Metric.domain == domain)
        return statement
