"""`POST /measurements` es un upsert por fecha: no debe borrar lo que ya había."""


async def test_a_second_measurement_on_the_same_day_keeps_the_fields_it_does_not_send(
    registered_client,
):
    client, _user_id = registered_client
    day = "2026-03-01"
    first = await client.post(
        "/api/measurements",
        json={"measured_on": day, "weight_kg": 80.5, "source": "health_connect"},
    )
    assert first.status_code == 201

    second = await client.post("/api/measurements", json={"measured_on": day, "waist_cm": 90})
    assert second.status_code == 201
    body = second.json()
    assert body["weight_kg"] == 80.5  # antes se perdía (se sobrescribía con null)
    assert body["waist_cm"] == 90

    listed = (await client.get("/api/measurements")).json()
    assert len([m for m in listed if m["measured_on"] == day]) == 1


async def test_an_explicit_null_does_not_erase_an_existing_value_either(registered_client):
    client, _user_id = registered_client
    day = "2026-03-02"
    await client.post("/api/measurements", json={"measured_on": day, "weight_kg": 70})
    resp = await client.post(
        "/api/measurements", json={"measured_on": day, "weight_kg": None, "neck_cm": 38}
    )
    assert resp.json()["weight_kg"] == 70
    assert resp.json()["neck_cm"] == 38


async def test_a_new_day_still_stores_what_it_is_given(registered_client):
    client, _user_id = registered_client
    resp = await client.post(
        "/api/measurements", json={"measured_on": "2026-03-03", "weight_kg": 65, "hip_cm": 100}
    )
    assert resp.status_code == 201
    assert (resp.json()["weight_kg"], resp.json()["hip_cm"]) == (65, 100)
    assert resp.json()["source"] == "manual"
