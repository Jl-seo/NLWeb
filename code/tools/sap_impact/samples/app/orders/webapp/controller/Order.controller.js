sap.ui.define([
  "sap/ui/core/mvc/Controller",
  "orders/model/formatter"
], function (Controller, formatter) {
  "use strict";
  return Controller.extend("orders.controller.Order", {
    formatter: formatter,
    onOpenDialog: function () {
      this.loadFragment({ name: "orders.view.OrderDialog" });
    }
  });
});
