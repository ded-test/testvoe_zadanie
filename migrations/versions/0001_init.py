"""начальная схема
пишу сырым sql потому что ограничения ниже это и есть вся защита от двойных списаний и возвратов
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE users (
            id         uuid PRIMARY KEY,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        """
    )

    # модели и их цена в токена
    op.execute(
        """
        CREATE TABLE models (
            slug         text PRIMARY KEY,
            price_tokens integer NOT NULL
        );
        """
    )

    # нога = модель + провайдера      вместе первичный ключ
    op.execute(
        """
        CREATE TABLE legs (
            model_slug         text NOT NULL REFERENCES models(slug) ON DELETE CASCADE,
            provider           text NOT NULL,
            priority           integer NOT NULL,
            max_ref_images     integer NOT NULL DEFAULT 0,
            skip_on_moderation boolean NOT NULL DEFAULT false,
            PRIMARY KEY (model_slug, provider),
            UNIQUE (model_slug, priority)
        );
        """
    )

    op.execute(
        """
        CREATE TABLE tasks (
            id           uuid PRIMARY KEY,
            user_id      uuid NOT NULL REFERENCES users(id),
            model_slug   text NOT NULL REFERENCES models(slug),
            prompt       text NOT NULL,
            ref_images   jsonb NOT NULL DEFAULT '[]'::jsonb,
            price_tokens integer NOT NULL,
            status       text NOT NULL,
            error_type   text,
            result_url   text,
            created_at   timestamptz NOT NULL DEFAULT now(),
            finished_at  timestamptz
        );
        """
    )
    op.execute("CREATE INDEX tasks_user_idx ON tasks (user_id);")

    # попытка одной ноги        сюда приходят вебхуки провайдера
    op.execute(
        """
        CREATE TABLE task_attempts (
            id           uuid PRIMARY KEY,
            task_id      uuid NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            leg_priority integer NOT NULL,
            provider     text NOT NULL,
            status       text NOT NULL,
            error_type   text,
            external_id  text,
            result_url   text,
            error_detail text,
            deadline_at  timestamptz,
            created_at   timestamptz NOT NULL DEFAULT now(),
            finished_at  timestamptz,
            UNIQUE (task_id, leg_priority)
        );
        """
    )
    # один и тот же калбек провайдера не должен попасть в две попытки 
    op.execute(
        "CREATE UNIQUE INDEX task_attempts_external_idx ON task_attempts (provider, external_id);"
    )

    # журнал денег уникальный ключ и есть защита от двойных операций
    op.execute(
        """
        CREATE TABLE ledger_entries (
            id              serial PRIMARY KEY,
            user_id         uuid NOT NULL REFERENCES users(id),
            amount          integer NOT NULL,
            kind            text NOT NULL,
            idempotency_key text NOT NULL UNIQUE,
            task_id         uuid,
            payment_id      text,
            created_at      timestamptz NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("CREATE INDEX ledger_entries_user_idx ON ledger_entries (user_id);")

    # одна оплата = одна строка, айлишник первичный ключ
    op.execute(
        """
        CREATE TABLE payments (
            payment_id text PRIMARY KEY,
            user_id    uuid NOT NULL REFERENCES users(id),
            tokens     integer NOT NULL,
            status     text NOT NULL,
            payload    jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        """
    )


def downgrade() -> None:
    for table in (
        "payments",
        "ledger_entries",
        "task_attempts",
        "tasks",
        "legs",
        "models",
        "users",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table};")
