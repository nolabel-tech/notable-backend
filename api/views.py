import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import User, Message
from .models import User, Contact
from .serializers import UserSerializer, RegisterSerializer, LoginSerializer, MessageSerializer, UpdateUserSerializer
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from rest_framework.views import APIView


class RegisterView(APIView):
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            return Response({"token": user.token, "unique": user.unique}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class LoginView(APIView):
    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')

        try:
            user = User.objects.get(username=username)
            if user.check_password(password):
                if user.is_active:
                    return Response({"token": user.token, "unique": user.unique}, status=status.HTTP_200_OK)
                else:
                    return Response({"error": "Account is disabled."}, status=status.HTTP_403_FORBIDDEN)
            else:
                return Response({"error": "Invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED)
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

class ContactView(APIView):
    def post(self, request):
        try:
            user = User.objects.get(username=request.data.get('username'), email=request.data.get('email'))
            return Response({"unique": user.unique}, status=status.HTTP_200_OK)
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

class SendMessageView(APIView):
    def post(self, request):
        recipient_unique = request.data.get('unique')
        message_content = request.data.get('message')
        from_user_unique = request.data.get('from_user')

        try:
            recipient = User.objects.get(unique=recipient_unique)
            from_user = User.objects.get(unique=from_user_unique)

            # Создаем сообщение в базе данных
            message = Message.objects.create(
                sender=from_user,
                recipient=recipient,
                content=message_content
            )
            message.delivered = True
            message.save()

            # Добавляем отправителя в контакты получателя, если его там еще нет
            if not recipient.contacts.filter(unique=from_user_unique).exists():
                recipient.contacts.add(from_user)
                recipient.save()

            return Response(
                {"message": "Message sent successfully", "from": from_user.username, "to": recipient.username},
                status=200)
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=404)


class CheckMessagesView(APIView):
    def get(self, request, unique):
        try:
            user = User.objects.get(unique=unique)
            messages = Message.objects.filter(recipient=user, delivered=False)
            messages.update(delivered=True)
            serializer = MessageSerializer(messages, many=True)
            return Response(serializer.data)
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)


logger = logging.getLogger(__name__)

class AddContactView(APIView):
    def post(self, request):
        try:
            username = request.data.get('username')
            email = request.data.get('email')
            contact_user = User.objects.get(username=username, email=email)
            current_user = User.objects.get(unique=request.data.get('unique'))

            # Создаем уникальный идентификатор комнаты
            ids = sorted([current_user.unique, contact_user.unique])
            room_id = '_'.join(ids)

            # Проверяем, существует ли уже такой контакт у текущего пользователя
            if not Contact.objects.filter(user=current_user, contact=contact_user).exists():
                Contact.objects.create(user=current_user, contact=contact_user, room_id=room_id)
            
            # Проверяем, существует ли уже такой контакт у контактного пользователя
            if not Contact.objects.filter(user=contact_user, contact=current_user).exists():
                Contact.objects.create(user=contact_user, contact=current_user, room_id=room_id)

                # Уведомление второго пользователя о добавлении контакта
                channel_layer = get_channel_layer()
                async_to_sync(channel_layer.group_send)(
                    f"user_{contact_user.unique}",
                    {
                        "type": "contact.added",
                        "message": {
                            "username": current_user.username,
                            "email": current_user.email,
                            "unique": current_user.unique,
                            "room_id": room_id
                        }
                    }
                )

            return Response({"room_id": room_id, "unique": contact_user.unique}, status=status.HTTP_200_OK)
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error in AddContactView: {str(e)}")
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class UpdateUserView(APIView):
    def post(self, request):
        unique = request.data.get('unique')
        try:
            user = User.objects.get(unique=unique)
            serializer = UpdateUserSerializer(user, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response({"message": "User details updated successfully"}, status=status.HTTP_200_OK)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logging.error(f"Error in UpdateUserView: {str(e)}")
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)