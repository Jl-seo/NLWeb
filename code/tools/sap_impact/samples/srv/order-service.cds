using { sap.order as db } from '../db/schema';

service OrderService {
  entity Orders as projection on db.Orders;
}
