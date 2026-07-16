# Pendientes — domain-foundation-core

## 1. Panel de revisión incompleto (secciones 4-7)

- **Fase**: run · **Tipo**: `deferred`
- **Qué**: el panel (architect/security/qa) solo completó las secciones 1-3 (PASS tras 4 findings corregidos, ver design.md D16). Las secciones 4-6 (properties/guests/reservations) se interrumpieron a mitad por límite de uso de la sesión; la sección 7 (timeline) no se revisó.
- **Por qué importa**: la implementación se auto-verificó (18/18 tests, DDL compilado, round-trip de migración) pero eso no sustituye al panel adversarial — el propio run encontró 3 bugs más por su cuenta (NullType FK en columnas cross-módulo, ENUMs huérfanos en el downgrade), señal de que el panel probablemente encontraría más en lo no revisado.
- **Reanudar con**: `/sdd:review domain-foundation-core` (panel a escala feature — cubre las secciones pendientes y las interacciones entre todas). Disponible tras el reset del límite (~00:20 Europe/Madrid).
- **Regla**: NO archivar antes de resolver esta entrada.
