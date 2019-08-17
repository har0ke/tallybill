
function set_side(){
    $("#footer").css("border-left", "1px #e0e0e0 solid").css("width", "300px")
        .css("height", "auto").css("top", "51px").css("border-top", "0");
    $("#main-container").css("width", "calc(100% - 300px)").css("margin", "0");
    $("#footer-opener").css("display", "none");
    $("#footer-summary").css("display", "none");
}
function set_bottom(){
    var activated;
    var height = "44px";
    if ($("#footer-opener").hasClass("glyphicon-menu-down"))
        height = "100%";
    $("#footer").css("border-left", "0").css("width", "100%")
        .css("height", height).css("top", "").css("border-top", "");
    $("#main-container").css("width", "").css("margin", "")
    $("#footer-opener").css("display", "");
    $("#footer-summary").css("display", "");
}

function set_width(count) {
    var ones = $(".product-button-one");
    var f_one = $(ones[0]);
    var width = Math.floor($("#product-wrapper").width() / count);
    var total_width = $($(".product-button")[0]).outerWidth(false);
    var one_width = (f_one[0].offsetWidth -
        parseFloat(f_one.css("padding-right")) - parseFloat(f_one.css("padding-left")) -
        parseFloat(f_one.css("border-right-width")) - parseFloat(f_one.css("border-left-width")));
    var rest = (total_width - one_width);
    console.log([count, width, total_width, one_width, rest])
    width = width - rest - 2 * 10;
    if (count == 1) {
        width -= 5;
    }
    console.log([width]);
    $(".product-button-one").width(width - 5);
}

function resize_buttons() {
    var width = $(window).width();
    if (width < 800) {
        set_bottom()
    } else {
        set_side()
    }
    if (width < 390) {
        set_width(1)
    } else {
        if (width < 600) {
            set_width(2)
        } else {

            if (width < 1000) {
                set_width(3)
            } else {
                if (width < 1400) {
                    set_width(4)
                } else {
                    set_width(5)
                }
            }
        }
    }
}

function click_popup() {
    console.log("done")
    var a_class = "glyphicon-menu-up";
    var d_class = "glyphicon-menu-down";
    var activate = $("#footer-opener").hasClass(a_class);
    $(".footer-height").each(function (i, item) {
        if (activate) {

            $(item).animate({height: '100%'}, 200);
            //item.style.height = "100%";
            $("#footer-opener").addClass(d_class);
            $("#footer-opener").removeClass(a_class);

        } else {
            $(item).animate({height: '44px'}, 200);
            $("#footer-opener").addClass(a_class);
            $("#footer-opener").removeClass(d_class);
        }
    });
    resize_buttons();
}
function get_current_products() {
    $("#json_data").valueOf()
}
function add_product(prod_id) {

}

String.prototype.format = function() {
  a = this;
  for (k in arguments) {
    a = a.replace("{" + k + "}", arguments[k])
  }
  return a
};

function dbClearOrderList() {
    $.cookie("orderList", "{}");
}
function getOrderList() {
    var jsonOrderList = $.cookie("orderList");
    if(!jsonOrderList) {
        jsonOrderList = "{}";
    }
    return JSON.parse(jsonOrderList);
}

function setOrderList(orderList) {
    $.cookie("orderList", JSON.stringify(orderList));
}

function dbAddToOrderList(product, user, count){
    var ol = getOrderList();
    if (!(user in ol))
        ol[user] = {};
    if (!(product in ol[user]))
        ol[user][product] = 0;
    ol[user][product] += count;
    setOrderList(ol);
}

function dbRemoveFromOrderList(product, user, count) {
    var ol = getOrderList();
    if (user in ol && product in ol[user])
        ol[user][product] -= max(count, ol[user][product]);
    setOrderList(ol);
}

function htmlRefreshOrderList() {
    htmlClearOrderList();
    var ol = getOrderList();
    var total = 0;
    for(var user in ol)
        for (var product in ol[user])
            if (user && product && ol[user][product]) {
                total += ol[user][product];
                htmlInsertToOrderList(id_to_getr[product], id_to_user[user], ol[user][product]);
            }
    $("#total-getr").html(total);
    $("#json_data").val(JSON.stringify(ol));
    console.log( $("#total-getr"));
}

function htmlClearOrderList() {
    $("#order-list").html("");
}

function htmlInsertToOrderList(product, user, count) {
    var template = " <tr>\n" +
        "   <th>{0}</th>\n" +
        "   <th>{1}</th>\n" +
        "   <th>{2}</th>\n" +
        "</tr>";
    $("#order-list").html($("#order-list").html() + template.format(product, user, count));
}

$(window).on("load", function() {
    htmlRefreshOrderList();
});
