"""Каталог моделей и ног (data-миграция 0002).

image-fast: 2 токена
  alpha — до 4 референсов (приоритет 1)
  beta  — до 10 референсов (приоритет 2)

video-long: 25 токенов
  beta  — до 2 референсов (приоритет 1)
  alpha — до 1 референса, skip_on_moderation (приоритет 2)
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO models (slug, price_tokens) VALUES
            ('image-fast', 2),
            ('video-long', 25)
        ON CONFLICT (slug) DO NOTHING;
        """
    )
    op.execute(
        """
        INSERT INTO legs (model_slug, provider, priority, max_ref_images, skip_on_moderation)
        VALUES
            ('image-fast', 'alpha', 1, 4,  false),
            ('image-fast', 'beta',  2, 10, false),
            ('video-long', 'beta',  1, 2,  false),
            ('video-long', 'alpha', 2, 1,  true)
        ON CONFLICT (model_slug, provider) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM legs WHERE model_slug IN ('image-fast', 'video-long');")
    op.execute("DELETE FROM models WHERE slug IN ('image-fast', 'video-long');")
