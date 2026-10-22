import { useEffect, useState } from "react";
import { api } from "../api.js";
import Badge from "./Badge.jsx";
import Table from "./Table.jsx";

const ORDER_COLUMNS = [
  ["PO", (order) => order.po_id],
  ["Product", (order) => order.product_name || order.sku],
  ["Supplier", (order) => order.supplier_name || order.supplier_id],
  ["Qty", (order) => order.quantity],
  ["Confirmed", (order) => order.confirmed_qty ?? "-"],
  ["Status", (order) => <Badge value={order.status} />],
  ["Expected day", (order) => order.expected_day ?? "-"],
  ["Created by", (order) => order.created_by],
  ["Run", (order) => order.run_id || "-"],
];

export default function OrdersTab({ onError }) {
  const [orders, setOrders] = useState([]);

  useEffect(() => {
    api.listOrders().then(setOrders).catch((err) => onError(err.message));
  }, []);

  return (
    <div className="card">
      <h2>Purchase orders</h2>
      <OrdersTable orders={orders} />
    </div>
  );
}

export function OrdersTable({ orders }) {
  return <Table columns={ORDER_COLUMNS} rows={orders} rowKey="po_id" />;
}
