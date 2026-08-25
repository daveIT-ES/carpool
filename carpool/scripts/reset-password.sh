#!/usr/bin/env bash
# Restablece la contrasena de cualquier usuario, incluido el administrador.
# Uso:  ./scripts/reset-password.sh correo@ejemplo.com
set -euo pipefail
cd "$(dirname "$0")/.."

CORREO="${1:-}"
if [ -z "$CORREO" ]; then
  echo "Uso: ./scripts/reset-password.sh correo@ejemplo.com"
  echo
  echo "Usuarios existentes:"
  docker compose exec -T app python -c "
from sqlmodel import Session, select
from app.database import engine
from app.models import User
with Session(engine) as s:
    for u in s.exec(select(User)).all():
        print(f'  {u.email:35} {u.alias:15} {u.role.value}')
" 2>/dev/null || echo "  (no se ha podido consultar: esta el servicio arrancado?)"
  exit 1
fi

read -rsp "Nueva contrasena (minimo 8 caracteres): " P1; echo
read -rsp "Repitela: " P2; echo
[ "$P1" = "$P2" ] || { echo "ERROR: no coinciden."; exit 1; }
[ ${#P1} -ge 8 ] || { echo "ERROR: minimo 8 caracteres."; exit 1; }

NUEVA="$P1" CORREO="$CORREO" docker compose exec -T -e NUEVA -e CORREO app python - <<'PYEOF'
import os
from sqlmodel import Session, select
from app.database import engine
from app.models import User
from app.security import hash_password

correo = os.environ["CORREO"].strip().lower()
with Session(engine) as s:
    u = s.exec(select(User).where(User.email == correo)).first()
    if u is None:
        raise SystemExit(f"No existe ningun usuario con el correo {correo}")
    u.password_hash = hash_password(os.environ["NUEVA"])
    u.is_active = True
    s.add(u)
    s.commit()
    print(f"Hecho. Contrasena de '{u.alias}' ({u.role.value}) actualizada.")
PYEOF
