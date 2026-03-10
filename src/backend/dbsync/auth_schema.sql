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

-- v1.1: Email+password authentication
ALTER TABLE auth."user" ADD COLUMN IF NOT EXISTS password_hash TEXT;
ALTER TABLE auth."user" ADD COLUMN IF NOT EXISTS email_verified BOOLEAN DEFAULT false;
ALTER TABLE auth."user" ADD COLUMN IF NOT EXISTS login_method TEXT DEFAULT 'token';

CREATE UNIQUE INDEX IF NOT EXISTS idx_user_email_unique
  ON auth."user"(LOWER(email))
  WHERE email IS NOT NULL;

CREATE TABLE IF NOT EXISTS auth.login_attempt (
    id SERIAL PRIMARY KEY,
    email TEXT,
    ip_address TEXT,
    success BOOLEAN NOT NULL DEFAULT false,
    attempted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_login_attempt_email_time
  ON auth.login_attempt(email, attempted_at)
  WHERE NOT success;

CREATE INDEX IF NOT EXISTS idx_login_attempt_ip_time
  ON auth.login_attempt(ip_address, attempted_at)
  WHERE NOT success;

-- v1.1 A1: Email verification tokens
CREATE TABLE IF NOT EXISTS auth.email_verification (
    id          SERIAL PRIMARY KEY,
    user_id     uuid NOT NULL REFERENCES auth."user"(id) ON DELETE CASCADE,
    token_hash  text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz NOT NULL DEFAULT (now() + interval '24 hours'),
    used_at     timestamptz
);

CREATE INDEX IF NOT EXISTS idx_email_verification_token_hash
  ON auth.email_verification(token_hash);

-- v1.1 A2: Password reset tokens
ALTER TABLE auth."user" ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS auth.password_reset (
    id          SERIAL PRIMARY KEY,
    user_id     uuid NOT NULL REFERENCES auth."user"(id) ON DELETE CASCADE,
    token_hash  text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz NOT NULL DEFAULT (now() + interval '1 hour'),
    used_at     timestamptz,
    ip_address  text
);

CREATE INDEX IF NOT EXISTS idx_password_reset_token_hash
  ON auth.password_reset(token_hash);
