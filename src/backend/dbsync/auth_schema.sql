CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS auth;

CREATE TABLE IF NOT EXISTS auth."user" (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    display_name        text NOT NULL,
    email               text,
    status              text NOT NULL DEFAULT 'active',
    is_service_account  boolean NOT NULL DEFAULT false,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    last_login_at       timestamptz
);

CREATE TABLE IF NOT EXISTS auth.role (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code                text NOT NULL UNIQUE,
    label               text NOT NULL,
    description         text,
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS auth.user_role (
    user_id             uuid NOT NULL REFERENCES auth."user"(id) ON DELETE CASCADE,
    role_id             uuid NOT NULL REFERENCES auth.role(id) ON DELETE CASCADE,
    created_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, role_id)
);

CREATE TABLE IF NOT EXISTS auth.api_token (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             uuid NOT NULL REFERENCES auth."user"(id) ON DELETE CASCADE,
    token_id            text NOT NULL UNIQUE,
    token_label         text NOT NULL,
    status              text NOT NULL DEFAULT 'active',
    last_used_at        timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_auth_user_status ON auth."user"(status);
CREATE INDEX IF NOT EXISTS idx_auth_api_token_user ON auth.api_token(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_api_token_status ON auth.api_token(status);

INSERT INTO auth.role (code, label, description)
VALUES
    ('user', 'User', 'Authenticated product user'),
    ('admin', 'Admin', 'Administrative access')
ON CONFLICT (code) DO NOTHING;
