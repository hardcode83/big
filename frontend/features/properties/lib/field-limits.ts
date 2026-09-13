/**
 * Client-side bound constants mirroring `backend/app/properties/api/schemas.py:41-52`
 * (design D5, R1.3). Each constant comments the exact backend line it mirrors so a
 * drift is easy to spot; a mismatch fails safe — a stale, too-generous frontend bound
 * still gets caught by the backend's real `422`, it just skips the earlier, friendlier
 * check (design D5, Risks).
 */

// schemas.py:41
export const MAX_NAME = 200;
// schemas.py:42
export const MAX_INTERNAL_CODE = 50;
// schemas.py:43
export const MAX_PMS_EXTERNAL_ID = 200;
// schemas.py:44
export const MAX_ADDRESS = 200;
// schemas.py:45
export const MAX_CITY = 100;
// schemas.py:46
export const MAX_PROVINCE = 100;
// schemas.py:47
export const MAX_POSTAL_CODE = 20;
// schemas.py:48
export const MAX_WIFI_NAME = 200;
// schemas.py:53
export const MAX_NOTES = 5000;
// schemas.py:54
export const MAX_WIFI_PASSWORD = 200;
// schemas.py:57
export const MAX_GUESTS = 50;
// schemas.py:58
export const MAX_ROOMS = 50;
