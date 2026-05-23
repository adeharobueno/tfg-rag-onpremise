import jwt
print(jwt.encode({"department": "TEST_RRHH", "role": "manager"}, "ETSIIT_UGR_SECRET_KEY_2026", algorithm="HS256"))
