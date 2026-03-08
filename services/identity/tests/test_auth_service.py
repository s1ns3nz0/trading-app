"""Unit tests for AuthService."""

import pytest
from unittest.mock import AsyncMock, patch

from app.services.auth_service import AuthService, AuthError, MAX_LOGIN_ATTEMPTS
from app.models.user import User, UserStatus


# ──────────────────────────────────────────────
# Register
# ──────────────────────────────────────────────

class TestRegister:
    @pytest.mark.asyncio
    async def test_register_success(self, mock_repo):
        new_user = User(email="alice@example.com", username="alice", hashed_password="x")
        mock_repo.find_by_email.return_value = None
        mock_repo.save.return_value = new_user
        svc = AuthService(mock_repo)
        result = await svc.register("alice@example.com", "alice", "password123")
        assert result.email == "alice@example.com"
        mock_repo.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_register_duplicate_email_raises_409(self, mock_repo, active_user):
        mock_repo.find_by_email.return_value = active_user
        svc = AuthService(mock_repo)
        with pytest.raises(AuthError) as exc:
            await svc.register("alice@example.com", "alice2", "password123")
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_register_hashes_password(self, mock_repo):
        saved: list[User] = []
        mock_repo.find_by_email.return_value = None
        mock_repo.save.side_effect = lambda u: saved.append(u) or u
        svc = AuthService(mock_repo)
        await svc.register("x@y.com", "xuser", "mypassword")
        assert saved[0].hashed_password != "mypassword"
        assert saved[0].hashed_password.startswith("$2b$")


# ──────────────────────────────────────────────
# Login
# ──────────────────────────────────────────────

class TestLogin:
    @pytest.mark.asyncio
    async def test_login_rate_limited(self, mock_repo):
        mock_repo.get_login_attempts.return_value = MAX_LOGIN_ATTEMPTS
        svc = AuthService(mock_repo)
        with pytest.raises(AuthError) as exc:
            await svc.login("alice@example.com", "pw")
        assert exc.value.status_code == 429

    @pytest.mark.asyncio
    async def test_login_pending_verification_raises_403(self, mock_repo, pending_user):
        mock_repo.get_login_attempts.return_value = 0
        mock_repo.find_by_email.return_value = pending_user
        svc = AuthService(mock_repo)
        with pytest.raises(AuthError) as exc:
            await svc.login("bob@example.com", "correctpassword")
        assert exc.value.status_code == 403
        assert "not verified" in exc.value.message

    @pytest.mark.asyncio
    async def test_login_invalid_credentials(self, mock_repo):
        mock_repo.get_login_attempts.return_value = 0
        mock_repo.find_by_email.return_value = None
        svc = AuthService(mock_repo)
        with pytest.raises(AuthError):
            await svc.login("alice@example.com", "wrongpassword")

    @pytest.mark.asyncio
    async def test_login_success_returns_token_pair(self, mock_repo, active_user):
        mock_repo.get_login_attempts.return_value = 0
        mock_repo.find_by_email.return_value = active_user
        svc = AuthService(mock_repo)
        access, refresh = await svc.login("alice@example.com", "correctpassword")
        assert isinstance(access, str)
        assert isinstance(refresh, str)
        assert access != refresh

    @pytest.mark.asyncio
    async def test_login_increments_attempt_on_wrong_password(self, mock_repo, active_user):
        mock_repo.get_login_attempts.return_value = 0
        mock_repo.find_by_email.return_value = active_user
        svc = AuthService(mock_repo)
        with pytest.raises(AuthError):
            await svc.login("alice@example.com", "wrongpassword")
        mock_repo.increment_login_attempt.assert_called_once()

    @pytest.mark.asyncio
    async def test_login_suspended_raises_403(self, mock_repo, active_user):
        active_user.status = UserStatus.SUSPENDED
        mock_repo.get_login_attempts.return_value = 0
        mock_repo.find_by_email.return_value = active_user
        svc = AuthService(mock_repo)
        with pytest.raises(AuthError) as exc:
            await svc.login("alice@example.com", "correctpassword")
        assert exc.value.status_code == 403


# ──────────────────────────────────────────────
# Token refresh
# ──────────────────────────────────────────────

class TestRefresh:
    @pytest.mark.asyncio
    async def test_refresh_revoked_token_raises_401(self, mock_repo, active_user):
        """When jti is in revocation table, refresh should be denied."""
        # Issue a real refresh token to test revocation path
        svc = AuthService(mock_repo)
        _, refresh_token = svc._issue_tokens(active_user.id)
        mock_repo.is_token_revoked.return_value = True
        mock_repo.find_by_id.return_value = active_user
        with pytest.raises(AuthError) as exc:
            await svc.refresh(refresh_token)
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_success_rotates_token(self, mock_repo, active_user):
        svc = AuthService(mock_repo)
        _, refresh_token = svc._issue_tokens(active_user.id)
        mock_repo.is_token_revoked.return_value = False
        mock_repo.find_by_id.return_value = active_user
        new_access, new_refresh = await svc.refresh(refresh_token)
        assert new_access
        assert new_refresh != refresh_token  # rotation produces new token
        mock_repo.revoke_token.assert_called_once()  # old jti revoked


# ──────────────────────────────────────────────
# Email verification
# ──────────────────────────────────────────────

class TestEmailVerification:
    @pytest.mark.asyncio
    async def test_verify_email_invalid_token_raises_400(self, mock_repo):
        mock_repo.get_verification_token.return_value = None
        svc = AuthService(mock_repo)
        with pytest.raises(AuthError) as exc:
            await svc.verify_email("invalid_or_expired_token")
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_verify_email_success_activates_user(self, mock_repo):
        mock_repo.get_verification_token.return_value = "user-123"
        svc = AuthService(mock_repo)
        await svc.verify_email("valid_token")
        mock_repo.activate_user.assert_called_once_with("user-123")
        mock_repo.delete_verification_token.assert_called_once_with("valid_token")

    @pytest.mark.asyncio
    async def test_send_verification_email_saves_token(self, mock_repo, active_user):
        mock_repo.find_by_id.return_value = active_user
        svc = AuthService(mock_repo)
        with patch.object(svc, "_ses_client"):
            await svc.send_verification_email(active_user.id, active_user.email)
        mock_repo.save_verification_token.assert_called_once()
        # token argument should be a URL-safe string
        call_args = mock_repo.save_verification_token.call_args
        token = call_args[0][0]
        assert len(token) > 20


# ──────────────────────────────────────────────
# Logout
# ──────────────────────────────────────────────

class TestLogout:
    @pytest.mark.asyncio
    async def test_logout_revokes_refresh_token(self, mock_repo, active_user):
        svc = AuthService(mock_repo)
        _, refresh_token = svc._issue_tokens(active_user.id)
        await svc.logout(refresh_token)
        mock_repo.revoke_token.assert_called_once()

    @pytest.mark.asyncio
    async def test_logout_invalid_token_does_not_raise(self, mock_repo):
        svc = AuthService(mock_repo)
        # Should not raise even with an invalid/expired token
        await svc.logout("not.a.valid.jwt")
        mock_repo.revoke_token.assert_not_called()
