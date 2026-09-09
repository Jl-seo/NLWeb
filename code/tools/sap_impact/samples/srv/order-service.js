const cds = require('@sap/cds');

module.exports = cds.service.impl(async function (srv) {
  const { Orders } = cds.entities('sap.order');

  srv.before('UPDATE', 'Orders', async (req) => {
    const existing = await SELECT.one.from(Orders).where({ orderId: req.data.orderId });
    if (!existing) req.error(404, 'order not found');
  });
});
