import os
import pwd
import subprocess

import paths_factory


def _uid_for_user(user):
    return pwd.getpwnam(user).pw_uid


def grant_lockscreen_model_access(user, model_path=None):
    """Allow the lockscreen process for user to read only that user's model."""
    uid = _uid_for_user(user)
    models_dir = str(paths_factory.user_models_dir_path())
    model_path = model_path or paths_factory.user_model_path(user)

    subprocess.run(["setfacl", "-m", f"u:{uid}:--x", models_dir], check=True)
    subprocess.run(["setfacl", "-m", f"u:{uid}:r--", model_path], check=True)


def revoke_lockscreen_model_access(user, model_path=None):
    """Remove lockscreen ACLs for a user model, ignoring already absent ACLs."""
    uid = _uid_for_user(user)
    models_dir = str(paths_factory.user_models_dir_path())
    model_path = model_path or paths_factory.user_model_path(user)

    if os.path.exists(model_path):
        subprocess.run(["setfacl", "-x", f"u:{uid}", model_path], check=False)
    subprocess.run(["setfacl", "-x", f"u:{uid}", models_dir], check=False)
