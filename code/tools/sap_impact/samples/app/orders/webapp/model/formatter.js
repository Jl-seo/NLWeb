sap.ui.define([], function () {
  "use strict";
  return {
    statusText: function (sStatus) { return sStatus === "A" ? "승인" : "대기"; }
  };
});
