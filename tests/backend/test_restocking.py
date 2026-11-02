"""
Tests for restocking recommendation and order endpoints.
"""
from datetime import datetime, timedelta


class TestRestockRecommendations:
    """Test suite for restocking recommendations."""

    def test_get_recommendations(self, client):
        """Test getting restocking candidates."""
        response = client.get("/api/restocking/recommendations")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

        for item in data:
            for field in ["sku", "name", "category", "trend", "quantity",
                          "unit_cost", "line_cost", "lead_time_days"]:
                assert field in item

    def test_recommendations_only_positive_gaps(self, client):
        """Test that only items with growing demand are recommended."""
        data = client.get("/api/restocking/recommendations").json()
        skus = [item["sku"] for item in data]

        # MTR-304 has decreasing demand and must not be restocked
        assert "MTR-304" not in skus
        for item in data:
            assert item["quantity"] == item["forecasted_demand"] - item["current_demand"]
            assert item["quantity"] > 0
            assert abs(item["line_cost"] - item["quantity"] * item["unit_cost"]) < 0.01

    def test_recommendations_ranking(self, client):
        """Test increasing trends come first, then largest gap."""
        data = client.get("/api/restocking/recommendations").json()
        keys = [(item["trend"] != "increasing", -item["quantity"]) for item in data]
        assert keys == sorted(keys)
        assert data[0]["trend"] == "increasing"


class TestRestockOrders:
    """Test suite for submitting restocking orders."""

    def test_orders_empty_initially(self, client):
        """Test no restocking orders exist before any are submitted."""
        response = client.get("/api/restocking/orders")
        assert response.status_code == 200
        assert response.json() == []

    def test_create_order(self, client):
        """Test creating a restocking order computes totals and lead time."""
        candidates = client.get("/api/restocking/recommendations").json()
        selected = candidates[:3]
        payload = {
            "budget": 1_000_000,
            "items": [{"sku": c["sku"], "quantity": c["quantity"]} for c in selected],
        }

        response = client.post("/api/restocking/orders", json=payload)
        assert response.status_code == 201

        order = response.json()
        assert order["status"] == "Submitted"
        assert order["order_number"] == "RST-0001"
        assert len(order["items"]) == 3
        assert abs(order["total_cost"] - sum(c["line_cost"] for c in selected)) < 0.01
        assert order["lead_time_days"] == max(c["lead_time_days"] for c in selected)

        order_date = datetime.fromisoformat(order["order_date"])
        expected = datetime.fromisoformat(order["expected_delivery"])
        assert expected - order_date == timedelta(days=order["lead_time_days"])

    def test_created_order_is_listed(self, client):
        """Test submitted orders appear in the list, newest first."""
        candidates = client.get("/api/restocking/recommendations").json()
        for c in candidates[:2]:
            payload = {"budget": 1_000_000, "items": [{"sku": c["sku"], "quantity": c["quantity"]}]}
            assert client.post("/api/restocking/orders", json=payload).status_code == 201

        data = client.get("/api/restocking/orders").json()
        assert [o["order_number"] for o in data] == ["RST-0002", "RST-0001"]

    def test_server_ignores_client_quantity(self, client):
        """Test quantity comes from the recommendation, not the request."""
        candidate = client.get("/api/restocking/recommendations").json()[0]
        payload = {"budget": 1_000_000, "items": [{"sku": candidate["sku"], "quantity": 999999}]}

        order = client.post("/api/restocking/orders", json=payload).json()
        assert order["items"][0]["quantity"] == candidate["quantity"]

    def test_create_order_empty_items(self, client):
        """Test an order with no items is rejected."""
        response = client.post("/api/restocking/orders", json={"budget": 1000, "items": []})
        assert response.status_code == 400

    def test_create_order_unknown_sku(self, client):
        """Test an order with a non-candidate SKU is rejected."""
        payload = {"budget": 1000, "items": [{"sku": "NOPE-000", "quantity": 1}]}
        response = client.post("/api/restocking/orders", json=payload)
        assert response.status_code == 400
        assert "NOPE-000" in response.json()["detail"]

    def test_create_order_over_budget(self, client):
        """Test an order costing more than the budget is rejected."""
        candidate = client.get("/api/restocking/recommendations").json()[0]
        payload = {
            "budget": candidate["line_cost"] - 1,
            "items": [{"sku": candidate["sku"], "quantity": candidate["quantity"]}],
        }
        response = client.post("/api/restocking/orders", json=payload)
        assert response.status_code == 400
        assert "budget" in response.json()["detail"].lower()
        assert client.get("/api/restocking/orders").json() == []

    def test_create_order_duplicate_sku(self, client):
        """Test an order listing the same SKU twice is rejected."""
        candidate = client.get("/api/restocking/recommendations").json()[0]
        item = {"sku": candidate["sku"], "quantity": candidate["quantity"]}
        response = client.post("/api/restocking/orders", json={"budget": 1_000_000, "items": [item, item]})
        assert response.status_code == 400

    def test_create_order_invalid_payload(self, client):
        """Test a malformed payload returns a validation error."""
        response = client.post("/api/restocking/orders", json={"items": []})
        assert response.status_code == 422
