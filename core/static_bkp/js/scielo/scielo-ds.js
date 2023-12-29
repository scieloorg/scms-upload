var ads__formControl = {
    ListenerNamespace: "ads",
    ListenerValidate: "ads-validate",
    Init: function() {
        var _self = this,
            fields = _self.SelectFields(),
            frm = _self.SelectNeedsValidation();

        fields.forEach(function() {
            _self.CheckIfHasLabel(this);
            _self.SetFieldWithValue(this);
            _self.CheckIfMultiple(this);
            _self.CheckIfPlaceholder(this);
            _self.CheckIfDisabled(this);
            _self.CheckIfSearch(this);
            _self.CheckIfDatepicker(this);
            _self.CheckSize(this);
            _self.ObserveFieldDisability(this);
            // _self.ApplyMask(this);
        });

        _self.ApplyChangeBehavior(fields);
        _self.ApplyFocusBlurBehavior(fields);
        //_self.ApplyKeyupBehavior(fields);
        _self.ApplySubmitBehavior(frm);
    },
    SelectFields: function() {
        var onlyVisibleItens = document.querySelectorAll(".ads__form-control > input, .ads__form-file > input"),
            itens = document.querySelectorAll(".ads__form-control > textarea, .ads__form-select > select");
        
        onlyVisibleItens.forEach(function() {
            var style = window.getComputedStyle(this);
            if(style && (style.display !== 'none') || (style.visibility !== 'hidden'))
                itens.push(this);
        });

        return itens;
    },
    SelectNeedsValidation: function() {
        return document.querySelectorAll(".needs-validation, .ads__form-needs-validation");
    },
    ApplyChangeBehavior: function(field) {
        var _self = this;

        if(field[0] && field[0].parentNode.classList.contains("ads__form-file"))
            _self.RecordOriginalLabel(field[0]);

        field.addEventListener("change."+_self.ListenerNamespace,function() {
            _self.SetFieldWithValue(this);
            _self.CheckIfDisabled(this);
            
            if(this.parentNode.classList.contains("b3__form-file")) {
                _self.SetFilenameToLabel(this);
            }
        });
    },
    ApplyFocusBlurBehavior: function(field) {
        var _self = this;

        field.addEventListener("focus."+_self.ListenerNamespace,function() {
            _self.SetFieldFocused(this,true);
        }).addEventListener("blur."+_self.ListenerNamespace,function() {
            _self.SetFieldFocused(this,false);
        });
    },
    ApplyKeyupBehavior: function(field) {
        var _self = this;

        field.addEventListener("blur."+_self.ListenerNamespace,function() {
            _self.SetValidInvalid(this);
        });
    },
    ApplySubmitBehavior: function(frm) {
        var _self = this;

        frm.addEventListener("submit."+_self.ListenerNamespace,function(e) {
            if (this.checkValidity() === false) {
                event.preventDefault();
                event.stopPropagation();
            }

            var fields = this.querySelectorAll('input:required:not([hidden]), select:required:not([hidden]), textarea:required:not([hidden])');
            fields.forEach(function(field) {
                _self.SetValidInvalid(field);
            });
            
            this.classList.add('was-validated');
        });
    },
    ApplyMask: function(field) {
        var _self = this,
            rtn = false,
            input = $(field),
            maskDefaults = {
                watchInterval: 10,
                clearIfNotMatch: true,
                dataMask: false,
                translation:  {
                    'a': {pattern: /[a-zA-Z]/},
                    '*': {pattern: /[a-zA-Z0-9]/},
                    '?': {pattern: /\d/, optional: true},
                    '9': {pattern: /\d/, optional: false},
                }
            };
        
        if(input.data("b3Mask") != undefined){
            var b3mask = input.data("b3Mask"),
                b3maskReverse = input.data("b3MaskReverse") != undefined && input.data("b3MaskReverse") == true ? true : false,
                maskToApply = _self.SetMaskValue(b3mask, input);

            if(maskToApply != null) 
                input.unmask().mask(maskToApply, !b3maskReverse ? maskDefaults : {reverse: true}).off("blur."+_self.ListenerValidate);

            input.addEventListener("change."+_self.ListenerValidate,function(){
                _self.SetMaskValidate(field, b3mask);
            });

            rtn = true;
        }
            
        return rtn;
    },
    SetMaskValue: function(mask) {
        var b3mask = "";

        switch(mask) {
            case "date":
                b3mask = "99/99/9999";
                break;
            case "time":
                b3mask = "00:00";
                break;
            case "phone":
                b3mask = "(99) 9999.9999?9";
                break;
            case "cpf":
                b3mask = "999.999.999-99";
                break;
            case "cnpj":
                b3mask = "99.999.999/9999-99";
                break;
            case "cep":
                b3mask = "99999-999";
                break;
            case "money":
                b3mask = "#.##0,00";
                break;
            case "email":
                b3mask = null;
                break;
            default:
                b3mask = mask;
                break;
        }

        return b3mask;
    },
    SetMaskValidate: function(field, mask) {
        var _self = this,
            status = false;

        switch(mask) {
            case "date":
                status = _self.ValidateDate(field.value);
                break;
            case "email":
                status = _self.ValidateMail(field.value);
                break;
            case "phone":
                status = _self.ValidatePhone(field.value);
                break;
            case "cpf":
                status = _self.ValidateCPF(field.value);
                break;
            case "cnpj":
                status = _self.ValidateCNPJ(field.value);
                break;
            case "time":
                status = _self.ValidateTime(field.value);
                break;
            default:
                status = true;
                break;
        }

        field.setAttribute("data-valid",status);
        _self.SetValidInvalid(field);
    },
    SetFieldWithValue: function(obj) {
        obj.parentNode.classList.toggle("has-value",obj.value != '');
    },
    CheckIfMultiple: function(obj) {
        obj.parentNode.classList.toggle("is-multiple",obj.multiple);
    },
    CheckIfPlaceholder: function(obj) {
        obj.parentNode.classList.toggle("has-placeholder",obj.placeholder && obj.placeholder != '')
    },
    CheckIfHasLabel: function(obj) {
        obj.parentNode.classList.toggle("not-label",obj.parentNode.querySelectorAll("label").length == 0);
    },
    CheckIfDisabled: function(obj) {
        obj.parentNode.classList.toggle("is-disabled",obj.disabled);
    },
    CheckIfSearch: function(obj) {
        obj.parentNode.classList.toggle("is-search",obj.type == 'search');
        obj.parentNode.parentNode.classList.toggle("is-search",obj.parentNode.parentNode.classList.contains("input-group"));
    },
    CheckIfDatepicker: function(obj) {
        obj.parentNode.classList.toggle("is-datepicker",obj.classList.contains("b3__form-datepicker"));
    },
    CheckSize: function(obj) {
        obj.parentNode.classList.toggle("large",obj.parentNode.classList.contains("large") || obj.classList.contains('form-control-lg'));
        obj.parentNode.classList.toggle("small",obj.parentNode.classList.contains("small") || obj.classList.contains('form-control-sm'));
    },
    SetFieldFocused: function(obj,focused) {
        obj.parentNode.classList.toggle("is-focused",focused);
    },
    SetValidInvalid: function(obj) {
        var dataValidate = typeof obj.dataset.valid != "undefined" ? true : false,
            parseValidate =  !dataValidate ? false : JSON.parse(obj.dataset.valid);

        obj.parentNode.classList.toggle("is-valid", dataValidate ? parseValidate : obj.validity.valid);
        obj.parentNode.classList.toggle("is-invalid", dataValidate ? !parseValidate : !obj.validity.valid);
    },
    RecordOriginalLabel: function(obj) {
        var label = obj.parentNode.querySelector("label");
        label.data("label",label.text());
    },
    SetFilenameToLabel: function(obj) {
        var filename = obj.value,
            label = obj.parentNode.querySelector("label");

        filename = filename.replace(/\\/g, '/').replace(/.*\//, '');

        if(filename == '') filename = label.data("label");
        label.html(filename);
    },
    ObserveFieldDisability: function(obj) {
        var observer = new MutationObserver(function(mutations) {
                for (var i=0, mutation; mutation = mutations[i]; i++) {
                    obj.parentNode.classList.toggle("is-disabled",mutation.attributeName == 'disabled' && mutation.target.disabled);
                }
            });
        
        observer.observe(obj, {attributes: true});
    },
    ValidateCPF: function(cpf) {
        var cpf = cpf.replace(/[^\d]+/g,'');

		var Soma;
		var Resto;
		Soma = 0;
		
		if (
				cpf == "00000000000" ||
				cpf == "11111111111" ||
				cpf == "22222222222" ||
				cpf == "33333333333" ||
				cpf == "44444444444" ||
				cpf == "55555555555" ||
				cpf == "66666666666" ||
				cpf == "77777777777" ||
				cpf == "88888888888" ||
				cpf == "99999999999"
			) return false;
	     
		for (i=1; i<=9; i++) Soma = Soma + parseInt(cpf.substring(i-1, i)) * (11 - i);
		Resto = (Soma * 10) % 11;
	     
		if ((Resto == 10) || (Resto == 11))  Resto = 0;
		if (Resto != parseInt(cpf.substring(9, 10)) ) return false;
	     
		Soma = 0;
		for (i = 1; i <= 10; i++) Soma = Soma + parseInt(cpf.substring(i-1, i)) * (12 - i);
		Resto = (Soma * 10) % 11;
	     
		if ((Resto == 10) || (Resto == 11))  Resto = 0;
		if (Resto != parseInt(cpf.substring(10, 11) ) ) return false;

		return true;
    },
	ValidateCNPJ: function(cnpj) {
		cnpj = cnpj.replace(/[^\d]+/g,'');
 
		if (cnpj == '') return false;
		if (cnpj.length != 14) return false;
 
		// Elimina CNPJs invalidos conhecidos
		if (cnpj == "00000000000000" || 
			cnpj == "11111111111111" || 
			cnpj == "22222222222222" || 
			cnpj == "33333333333333" || 
			cnpj == "44444444444444" || 
			cnpj == "55555555555555" || 
			cnpj == "66666666666666" || 
			cnpj == "77777777777777" || 
			cnpj == "88888888888888" || 
			cnpj == "99999999999999")
		return false;

		tamanho = cnpj.length - 2
		numeros = cnpj.substring(0,tamanho);
		digitos = cnpj.substring(tamanho);
		soma = 0;
		pos = tamanho - 7;

		for (i = tamanho; i >= 1; i--) {
			soma += numeros.charAt(tamanho - i) * pos--;
			if (pos < 2) pos = 9;
		}
		resultado = soma % 11 < 2 ? 0 : 11 - soma % 11;

		if (resultado != digitos.charAt(0)) return false;
         
		tamanho = tamanho + 1;
		numeros = cnpj.substring(0,tamanho);
		soma = 0;
		pos = tamanho - 7;
		for (i = tamanho; i >= 1; i--) {
			soma += numeros.charAt(tamanho - i) * pos--;
			if (pos < 2) pos = 9;
		}
		resultado = soma % 11 < 2 ? 0 : 11 - soma % 11;
		
		if (resultado != digitos.charAt(1)) return false;
           
		return true;
    },
    ValidatePhone: function(num) {
        var rtn = true;
        num = num.replace(/\(/g,"").replace(/\)/g,"").replace(/ /g,"").replace(/\./g,"");

        if(num !== "") {
            if(
                num.indexOf("0000000") > -1 ||
                num.indexOf("1111111") > -1 ||
                num.indexOf("2222222") > -1 ||
                num.indexOf("3333333") > -1 ||
                num.indexOf("4444444") > -1 ||
                num.indexOf("5555555") > -1 ||
                num.indexOf("6666666") > -1 ||
                num.indexOf("7777777") > -1 ||
                num.indexOf("8888888") > -1 ||
                num.indexOf("9999999") > -1
                ) {
                rtn = false;	
            } 
        }

        return rtn;
    },
	ValidateMail: function(email) { 
		var re = /^(([^<>()[\]\\.,;:\s@\"]+(\.[^<>()[\]\\.,;:\s@\"]+)*)|(\".+\"))@((\[[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\])|(([a-zA-Z\-0-9]+\.)+[a-zA-Z]{2,}))$/;
		return re.test(email);
    },
    ValidateDate: function(date) {
        var v = date,
            status = true;

        v = v.split("/");
        
        var vDate = new Date(v[2],(parseInt(v[1])-1),v[0]);

        if(v !== "" &&  (parseInt(v[0]) !== parseInt(vDate.getDate()) || parseInt(v[1]) !== (parseInt(vDate.getMonth())+1))) {
            status = false;
        }

        return status;
    },
    ValidateTime: function(time) {
        var status = true;

        time = time.split(":");

        if(parseInt(time[0]) > 23 || parseInt(time[1]) > 60)
            status = false;

        return status;
    }
};
var ads__organism = {
	Init: function() {
			this.Organism();
	},
	Organism: function() {
		var year = document.querySelector(".ads__footter-year");
		
		if(year !== null) {
			var d = new Date();
			year.innerHTML = d.getFullYear();
		}
	}
};
var ads__navControl = {
    Init: function() {
        this.DropdownContextFix();
    },
    DropdownContextFix: function() {
        document.querySelectorAll(".dropdown-pane, .dropdown-menu, .dropdown.menu .is-dropdown-submenu-parent, .card, .modal-dialog").forEach(function() {
            this.classList.add("ads__theme--light");
        });
    }
};
var ads__chart = {
	Colors: function(type, idx, rgba) {
		var rtn = [];

		colorsTypes = {
			bar: [
				'rgb(0, 176, 234)',
				'rgb(17, 50, 116)',
				'rgb(0, 62, 120)',
				'rgb(246, 168, 84)',
				'rgb(255, 216, 98)',
				'rgb(255, 216, 98)',
				'rgb(0, 92, 168)',
				'rgb(90, 196, 241)',
				'rgb(160, 217, 247)',
				'rgb(93, 96, 97)',
				'rgb(77, 77, 77)'
			],
			line: [
				'rgb(0, 52, 117)',
			],
			radar: [
				'rgb(102, 110, 122)',
				'rgb(0, 176, 230)'
			]
		}

		if(type == 'bar'|| type == 'pie' || type == 'doughnut') {
		   rtn = colorsTypes.bar;
		} else if(type == 'radar') {
			if(rgba === true)
				rtn = b3__chart.ConvertRGBToRGBA(colorsTypes.radar[idx]);
			else
				rtn = colorsTypes.radar[idx];
		} else
			rtn = colorsTypes.line;

		return rtn 
	},
	ConvertRGBToRGBA: function(color){
		var newColor = color.replace(/rgb/i, "rgba");

		newColor = newColor.replace(/\)/i,',0.2)');

		return newColor;
	},
	Init: function() {
		if(typeof Chart != "undefined") {
			Chart.defaults.global.defaultFontFamily = '"Muli",sans-serif';
			Chart.defaults.global.elements.arc.borderWidth = 0;
			Chart.defaults.global.elements.arc.hoverBorderWidth = 0;
		}
	}
}
var ads__datepicker = {
	globalConfigs: function() {
		jQuery.extend( jQuery.fn.pickadate.defaults, {
			monthsFull: [ 'janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro' ],
			monthsShort: [ 'jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez' ],
			weekdaysFull: [ 'domingo', 'segunda-feira', 'terça-feira', 'quarta-feira', 'quinta-feira', 'sexta-feira', 'sábado' ],
			weekdaysShort: [ 'dom', 'seg', 'ter', 'qua', 'qui', 'sex', 'sab' ],
			labelMonthNext: 'Próximo',
			labelMonthPrev: 'Anterior',
			today: 'hoje',
			clear: 'limpar',
			close: 'fechar',
			format: 'dd/mm/yyyy',
			formatSubmit: 'dd/mm/yyyy',
			onOpen: function() { document.querySelectorAll('pre').forEach(function() {
				this.style.overflow = 'hidden';
			})},
			onClose: function() { document.querySelectorAll('pre').forEach(function() {
				this.style.overflow = '';
			}) }
		});
	},
	Init: function() {
		if(typeof Picker != "undefined")
			this.globalConfigs();
	}
}
// require _components/_datagrid.js

document.addEventListener("DOMContentLoaded", function() {
    // ads__organism.Init();
    // ads__datagrid.Init();
    // ads__datepicker.Init();
    // ads__chart.Init();
    // ads__formControl.Init();
    // ads__navControl.Init();
    // ads__sidebar.Init();
});

//# sourceMappingURL=scielo-ds.js.map
