from myfood.ai.tools import (
    PROPOSE_MEAL_PLAN_TOOL_NAME,
    RESOLVE_FOOD_ITEMS_TOOL_NAME,
    build_propose_meal_plan_tool,
    build_resolve_food_items_tool,
)


def test_tool_has_expected_name_and_schema():
    tool_obj = build_propose_meal_plan_tool([])
    assert tool_obj.name == PROPOSE_MEAL_PLAN_TOOL_NAME
    assert tool_obj.input_schema["required"] == ["days"]
    assert "approx_portion" in str(tool_obj.input_schema)
    # R1: nunca aparece "grams"/"kcal" en el schema — el LLM no decide cantidades.
    schema_str = str(tool_obj.input_schema)
    assert "grams" not in schema_str
    assert "kcal" not in schema_str


async def test_tool_handler_appends_args_to_sink():
    sink: list[dict] = []
    tool_obj = build_propose_meal_plan_tool(sink)
    args = {"days": [{"day_index": 0, "meals": []}], "rationale": "test"}

    result = await tool_obj.handler(args)

    assert sink == [args]
    assert result["content"][0]["type"] == "text"


async def test_multiple_calls_all_appended_in_order():
    sink: list[dict] = []
    tool_obj = build_propose_meal_plan_tool(sink)

    await tool_obj.handler({"days": [], "rationale": "first"})
    await tool_obj.handler({"days": [], "rationale": "second"})

    assert [call["rationale"] for call in sink] == ["first", "second"]


async def test_different_sinks_are_independent():
    sink_a: list[dict] = []
    sink_b: list[dict] = []
    tool_a = build_propose_meal_plan_tool(sink_a)
    build_propose_meal_plan_tool(sink_b)

    await tool_a.handler({"days": []})

    assert len(sink_a) == 1
    assert len(sink_b) == 0


def test_resolve_food_items_tool_has_expected_name_and_schema():
    tool_obj = build_resolve_food_items_tool([])
    assert tool_obj.name == RESOLVE_FOOD_ITEMS_TOOL_NAME
    assert tool_obj.input_schema["required"] == ["items"]
    schema_str = str(tool_obj.input_schema)
    assert "approx_quantity_text" in schema_str
    # R1: la IA nunca calcula gramos ni valores nutricionales.
    assert "grams" not in schema_str
    assert "kcal" not in schema_str


async def test_resolve_food_items_handler_appends_args_to_sink():
    sink: list[dict] = []
    tool_obj = build_resolve_food_items_tool(sink)
    args = {"items": [{"alias": "c1", "approx_quantity_text": "dos"}]}

    result = await tool_obj.handler(args)

    assert sink == [args]
    assert result["content"][0]["type"] == "text"
